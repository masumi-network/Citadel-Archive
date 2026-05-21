from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from kb.service import Citadel

GITHUB_API = "https://api.github.com"
SOURCE_URL_TEMPLATE = "https://github.com/orgs/{org}/repositories"
STATE_VERSION = 1


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _short(value: str | None, *, length: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= length:
        return text
    return f"{text[: length - 1]}."


@dataclass(frozen=True)
class GitHubRepo:
    name: str
    full_name: str
    html_url: str
    description: str | None
    language: str | None
    pushed_at: str | None
    updated_at: str | None
    default_branch: str | None
    visibility: str | None
    archived: bool
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    topics: tuple[str, ...]
    license_name: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "GitHubRepo":
        license_data = data.get("license") or {}
        return cls(
            name=str(data.get("name") or ""),
            full_name=str(data.get("full_name") or ""),
            html_url=str(data.get("html_url") or ""),
            description=data.get("description"),
            language=data.get("language"),
            pushed_at=data.get("pushed_at"),
            updated_at=data.get("updated_at"),
            default_branch=data.get("default_branch"),
            visibility=data.get("visibility"),
            archived=bool(data.get("archived")),
            stargazers_count=int(data.get("stargazers_count") or 0),
            forks_count=int(data.get("forks_count") or 0),
            open_issues_count=int(data.get("open_issues_count") or 0),
            topics=tuple(data.get("topics") or ()),
            license_name=license_data.get("name"),
        )

    @property
    def fingerprint(self) -> str:
        parts = [
            self.pushed_at or "",
            self.updated_at or "",
            str(self.open_issues_count),
            self.default_branch or "",
            str(self.archived),
        ]
        return "|".join(parts)

    def state(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "pushed_at": self.pushed_at,
            "updated_at": self.updated_at,
            "open_issues_count": self.open_issues_count,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "url": self.html_url,
            "description": self.description,
            "language": self.language,
            "pushed_at": self.pushed_at,
            "updated_at": self.updated_at,
            "open_issues_count": self.open_issues_count,
            "stars": self.stargazers_count,
            "forks": self.forks_count,
            "topics": list(self.topics),
            "archived": self.archived,
        }


@dataclass(frozen=True)
class GitHubEvent:
    id: str
    type: str
    repo: str
    actor: str
    created_at: str
    summary: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "GitHubEvent":
        event_type = str(data.get("type") or "Event")
        payload = data.get("payload") or {}
        repo = (data.get("repo") or {}).get("name") or "unknown/repository"
        actor = (data.get("actor") or {}).get("login") or "unknown"
        return cls(
            id=str(data.get("id") or ""),
            type=event_type,
            repo=repo,
            actor=actor,
            created_at=str(data.get("created_at") or ""),
            summary=_event_summary(event_type, payload),
        )

    def summary_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "type": self.type,
            "repo": self.repo,
            "actor": self.actor,
            "created_at": self.created_at,
            "summary": self.summary,
        }


class GitHubAPIError(RuntimeError):
    pass


class GitHubOrgClient:
    def __init__(self, *, token: str | None = None, timeout: float = 20.0) -> None:
        self.token = token
        self.timeout = timeout

    def fetch_repos(self, org: str, *, max_repos: int) -> list[GitHubRepo]:
        repos: list[GitHubRepo] = []
        per_page = min(max(max_repos, 1), 100)
        page = 1
        while len(repos) < max_repos:
            data = self._get_json(
                f"/orgs/{org}/repos",
                {
                    "sort": "pushed",
                    "direction": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            if not isinstance(data, list):
                raise GitHubAPIError("GitHub returned an unexpected repositories payload.")
            repos.extend(GitHubRepo.from_api(item) for item in data)
            if len(data) < per_page:
                break
            page += 1
        return repos[:max_repos]

    def fetch_events(self, org: str, *, max_events: int) -> list[GitHubEvent]:
        events: list[GitHubEvent] = []
        per_page = min(max(max_events, 1), 100)
        page = 1
        while len(events) < max_events:
            data = self._get_json(
                f"/orgs/{org}/events",
                {
                    "per_page": per_page,
                    "page": page,
                },
            )
            if not isinstance(data, list):
                raise GitHubAPIError("GitHub returned an unexpected events payload.")
            events.extend(GitHubEvent.from_api(item) for item in data)
            if len(data) < per_page:
                break
            page += 1
        return events[:max_events]

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        query = urlencode(params)
        request = Request(
            f"{GITHUB_API}{path}?{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "citadel-archive-github-sync",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise GitHubAPIError(f"GitHub API returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GitHubAPIError(f"Could not reach GitHub API: {exc.reason}") from exc


class GitHubOrgSyncer:
    def __init__(
        self,
        citadel: Citadel,
        *,
        org: str | None = None,
        client: GitHubOrgClient | None = None,
        state_path: str | Path | None = None,
        max_repos: int | None = None,
        max_events: int | None = None,
        ingest_unchanged: bool | None = None,
        run_improve: bool | None = None,
    ) -> None:
        self.citadel = citadel
        self.config = citadel.config
        self.org = org or self.config.github_org
        self.client = client or GitHubOrgClient(token=self.config.github_token)
        self.state_path = Path(state_path or self.config.github_sync_state_path)
        self.max_repos = max_repos or self.config.github_sync_max_repos
        self.max_events = max_events or self.config.github_sync_max_events
        self.ingest_unchanged = (
            self.config.github_sync_ingest_unchanged
            if ingest_unchanged is None
            else ingest_unchanged
        )
        self.run_improve = self.config.github_sync_run_improve if run_improve is None else run_improve

    @classmethod
    def from_env(cls) -> "GitHubOrgSyncer":
        return cls(Citadel.from_env())

    async def status(self) -> dict[str, Any]:
        state = self._load_state()
        return {
            "ok": True,
            "org": self.org,
            "source_url": SOURCE_URL_TEMPLATE.format(org=self.org),
            "dataset": self.config.github_sync_dataset,
            "session_id": self.config.github_sync_session,
            "state_path": str(self.state_path),
            "last_checked_at": state.get("last_checked_at"),
            "last_digest_at": state.get("last_digest_at"),
            "tracked_repositories": len(state.get("repos") or {}),
            "seen_events": len(state.get("seen_event_ids") or []),
            "run_improve": self.run_improve,
            "ingest_unchanged": self.ingest_unchanged,
        }

    async def run(self, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        checked_at = utc_now()
        state = self._load_state()
        repos, events = await asyncio.to_thread(self._fetch_activity)
        previous_repos = state.get("repos") or {}
        previous_event_ids = set(state.get("seen_event_ids") or [])
        changed_repos = [
            repo
            for repo in repos
            if force or previous_repos.get(repo.full_name, {}).get("fingerprint") != repo.fingerprint
        ]
        new_events = [event for event in events if force or event.id not in previous_event_ids]
        should_ingest = force or self.ingest_unchanged or bool(changed_repos or new_events)
        digest = format_digest(
            org=self.org,
            checked_at=checked_at,
            repos=repos,
            changed_repos=changed_repos,
            events=new_events,
        )

        ingest_result = None
        improve_result = None
        if should_ingest and not dry_run:
            ingest_result = await self.citadel.ingest(
                digest,
                dataset=self.config.github_sync_dataset,
                session_id=self.config.github_sync_session,
                tags=["github", self.org, "daily-sync", "repository-activity"],
            )
            if ingest_result.accepted and self.run_improve:
                improve_result = await self.citadel.improve(
                    dataset=self.config.github_sync_dataset,
                    session_ids=[self.config.github_sync_session],
                )

        if not dry_run:
            state.update(
                {
                    "version": STATE_VERSION,
                    "org": self.org,
                    "last_checked_at": checked_at,
                    "repos": {repo.full_name: repo.state() for repo in repos},
                    "seen_event_ids": [
                        event.id for event in events if event.id
                    ][:500],
                }
            )
            if should_ingest:
                state["last_digest_at"] = checked_at
            self._save_state(state)

        return {
            "ok": True,
            "org": self.org,
            "source_url": SOURCE_URL_TEMPLATE.format(org=self.org),
            "checked_at": checked_at,
            "state_path": str(self.state_path),
            "repos_scanned": len(repos),
            "changed_count": len(changed_repos),
            "event_count": len(new_events),
            "changed_repositories": [repo.summary() for repo in changed_repos[:20]],
            "recent_events": [event.summary_dict() for event in new_events[:20]],
            "ingested": bool(ingest_result and ingest_result.accepted),
            "ingest_reason": getattr(ingest_result, "reason", None),
            "improved": improve_result is not None,
            "dry_run": dry_run,
            "digest": digest if dry_run else None,
        }

    def _fetch_activity(self) -> tuple[list[GitHubRepo], list[GitHubEvent]]:
        repos = self.client.fetch_repos(self.org, max_repos=self.max_repos)
        events = self.client.fetch_events(self.org, max_events=self.max_events)
        return repos, events

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": STATE_VERSION, "org": self.org, "repos": {}, "seen_event_ids": []}
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {"version": STATE_VERSION, "org": self.org, "repos": {}, "seen_event_ids": []}
        if not isinstance(data, dict):
            return {"version": STATE_VERSION, "org": self.org, "repos": {}, "seen_event_ids": []}
        data.setdefault("repos", {})
        data.setdefault("seen_event_ids", [])
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, sort_keys=True)
        temp_path.replace(self.state_path)


def format_digest(
    *,
    org: str,
    checked_at: str,
    repos: list[GitHubRepo],
    changed_repos: list[GitHubRepo],
    events: list[GitHubEvent],
) -> str:
    source_url = SOURCE_URL_TEMPLATE.format(org=org)
    lines = [
        f"# {org} GitHub daily update",
        "",
        f"Checked at: {checked_at}",
        f"Source: {source_url}",
        f"Repositories scanned: {len(repos)}",
        f"Changed repositories since last check: {len(changed_repos)}",
        f"New public organization events: {len(events)}",
        "",
        "## Changed repositories",
    ]

    if changed_repos:
        for repo in changed_repos[:20]:
            topics = f" Topics: {', '.join(repo.topics[:8])}." if repo.topics else ""
            description = _short(repo.description) or "No description."
            lines.append(
                "- "
                f"{repo.full_name} ({repo.language or 'unknown language'}): "
                f"pushed {repo.pushed_at or 'unknown'}, updated {repo.updated_at or 'unknown'}, "
                f"open issues {repo.open_issues_count}, stars {repo.stargazers_count}, "
                f"forks {repo.forks_count}. {description}{topics} {repo.html_url}"
            )
    else:
        lines.append("- No repository metadata changed since the last check.")

    lines.extend(["", "## Recent public activity"])
    if events:
        for event in events[:25]:
            lines.append(
                "- "
                f"{event.created_at}: {event.actor} on {event.repo}: "
                f"{event.type} - {event.summary}"
            )
    else:
        lines.append("- No new public org events were returned by GitHub.")

    lines.extend(["", "## Most recently pushed repositories"])
    for repo in repos[:10]:
        lines.append(
            "- "
            f"{repo.full_name}: pushed {repo.pushed_at or 'unknown'}; "
            f"language {repo.language or 'unknown'}; issues {repo.open_issues_count}; "
            f"{repo.html_url}"
        )

    return "\n".join(lines).strip()


def _event_summary(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "PushEvent":
        commits = payload.get("commits") or []
        messages = [_short(commit.get("message"), length=80) for commit in commits[:2]]
        ref = str(payload.get("ref") or "").removeprefix("refs/heads/")
        detail = "; ".join(message for message in messages if message)
        return f"Pushed {len(commits)} commit(s) to {ref or 'a branch'}" + (
            f": {detail}" if detail else ""
        )
    if event_type == "PullRequestEvent":
        pull_request = payload.get("pull_request") or {}
        return (
            f"{payload.get('action', 'updated')} pull request "
            f"#{pull_request.get('number')}: {_short(pull_request.get('title'), length=100)}"
        )
    if event_type == "PullRequestReviewEvent":
        pull_request = payload.get("pull_request") or {}
        review = payload.get("review") or {}
        return (
            f"{payload.get('action', 'reviewed')} review "
            f"{review.get('state', 'submitted')} on pull request "
            f"#{pull_request.get('number')}: {_short(pull_request.get('title'), length=100)}"
        )
    if event_type == "PullRequestReviewCommentEvent":
        pull_request = payload.get("pull_request") or {}
        comment = payload.get("comment") or {}
        return (
            f"{payload.get('action', 'commented')} review comment on pull request "
            f"#{pull_request.get('number')}: {_short(comment.get('body'), length=100)}"
        )
    if event_type == "IssuesEvent":
        issue = payload.get("issue") or {}
        return (
            f"{payload.get('action', 'updated')} issue "
            f"#{issue.get('number')}: {_short(issue.get('title'), length=100)}"
        )
    if event_type == "CreateEvent":
        return f"Created {payload.get('ref_type', 'ref')} {payload.get('ref') or ''}".strip()
    if event_type == "ReleaseEvent":
        release = payload.get("release") or {}
        return f"{payload.get('action', 'updated')} release {_short(release.get('name'), length=100)}"
    if event_type == "ForkEvent":
        forkee = payload.get("forkee") or {}
        return f"Forked to {forkee.get('full_name', 'a new repository')}"
    if event_type == "WatchEvent":
        return f"{payload.get('action', 'starred')} repository"
    return _short(event_type.replace("Event", " event"))


async def _sync_github(args: argparse.Namespace) -> None:
    syncer = GitHubOrgSyncer(
        Citadel.from_env(),
        org=args.org,
        state_path=args.state_path,
        max_repos=args.max_repos,
        max_events=args.max_events,
        ingest_unchanged=not args.skip_unchanged,
        run_improve=not args.skip_improve,
    )
    result = await syncer.run(force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kb.github_sync")
    parser.add_argument("--org", default=None, help="GitHub organization login")
    parser.add_argument("--state-path", default=None, help="Persistent sync state JSON path")
    parser.add_argument("--max-repos", type=int, default=None, help="Maximum repositories to scan")
    parser.add_argument("--max-events", type=int, default=None, help="Maximum org events to scan")
    parser.add_argument("--force", action="store_true", help="Treat all fetched activity as new")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print without ingesting")
    parser.add_argument("--skip-improve", action="store_true", help="Do not run Citadel improve")
    parser.add_argument(
        "--skip-unchanged",
        action="store_true",
        help="Skip ingest when GitHub reports no new activity",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_sync_github(args))


if __name__ == "__main__":
    main()
