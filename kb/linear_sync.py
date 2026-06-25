"""Linear workspace sync: org-wide issues → Central, assignee **Seat-Scoped Mirrors** → Nodes.

Read-only from Citadel's perspective — no write-back to Linear. Uses the Linear
GraphQL API with ``CITADEL_LINEAR_API_KEY``.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kb.access import CENTRAL_DATASET, SEAT_DATASET_PREFIX, AccessStore, seat_dataset
from kb.learning import LearningProcess
from kb.service import Citadel

logger = logging.getLogger(__name__)

LINEAR_API = "https://api.linear.app/graphql"
STATE_VERSION = 1


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _linear_state_path(configured: str | None) -> str:
    if configured:
        return configured
    root = Path("/data/.citadel" if Path("/data").exists() else ".citadel")
    return str(root / "linear_sync_state.json")


class LinearAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class LinearIssue:
    id: str
    identifier: str
    title: str
    description: str
    url: str
    priority: int
    updated_at: str
    state_name: str
    state_type: str
    team_key: str
    team_name: str
    assignee_id: str | None
    assignee_name: str | None
    assignee_email: str | None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> LinearIssue | None:
        if not isinstance(node, dict) or not node.get("id"):
            return None
        state = node.get("state") if isinstance(node.get("state"), dict) else {}
        team = node.get("team") if isinstance(node.get("team"), dict) else {}
        assignee = node.get("assignee") if isinstance(node.get("assignee"), dict) else {}
        identifier = str(node.get("identifier") or node.get("id") or "").strip()
        title = str(node.get("title") or identifier or "Untitled").strip()
        return cls(
            id=str(node["id"]),
            identifier=identifier,
            title=title,
            description=str(node.get("description") or "").strip(),
            url=str(node.get("url") or "").strip(),
            priority=int(node.get("priority") or 0),
            updated_at=str(node.get("updatedAt") or ""),
            state_name=str(state.get("name") or ""),
            state_type=str(state.get("type") or ""),
            team_key=str(team.get("key") or ""),
            team_name=str(team.get("name") or ""),
            assignee_id=str(assignee["id"]) if assignee.get("id") else None,
            assignee_name=str(assignee.get("name") or assignee.get("displayName") or "").strip()
            or None,
            assignee_email=str(assignee.get("email") or "").strip().lower() or None,
        )


ISSUES_QUERY = """
query Issues($first: Int!, $after: String) {
  issues(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      identifier
      title
      description
      url
      priority
      updatedAt
      state { name type }
      team { key name }
      assignee { id name email displayName }
    }
  }
}
"""


class LinearClient:
    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = Request(  # noqa: S310
            LINEAR_API,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LinearAPIError(f"Linear HTTP {exc.code}: {detail[:240]}") from exc
        except URLError as exc:
            raise LinearAPIError(f"Linear request failed: {exc.reason}") from exc
        if body.get("errors"):
            raise LinearAPIError(str(body["errors"])[:400])
        data = body.get("data")
        if not isinstance(data, dict):
            raise LinearAPIError("Linear response missing data")
        return data

    def fetch_issues(self, *, max_issues: int) -> list[LinearIssue]:
        issues: list[LinearIssue] = []
        cursor: str | None = None
        page_size = min(max(max_issues, 1), 100)
        while len(issues) < max_issues:
            data = self.query(
                ISSUES_QUERY,
                {"first": page_size, "after": cursor},
            )
            block = data.get("issues")
            if not isinstance(block, dict):
                break
            nodes = block.get("nodes")
            if not isinstance(nodes, list):
                break
            for raw in nodes:
                parsed = LinearIssue.from_node(raw)
                if parsed:
                    issues.append(parsed)
                    if len(issues) >= max_issues:
                        break
            page_info = block.get("pageInfo") if isinstance(block.get("pageInfo"), dict) else {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        return issues


def format_issue_note(issue: LinearIssue) -> str:
    lines = [
        f"# Linear {issue.identifier}: {issue.title}",
        "",
        f"- **State:** {issue.state_name or 'unknown'} ({issue.state_type or 'n/a'})",
        f"- **Team:** {issue.team_name or issue.team_key or 'unknown'}",
        f"- **Priority:** {issue.priority}",
        f"- **Updated:** {issue.updated_at or 'unknown'}",
    ]
    if issue.assignee_name:
        lines.append(f"- **Assignee:** {issue.assignee_name}")
    if issue.url:
        lines.append(f"- **URL:** {issue.url}")
    if issue.description:
        lines.append("")
        lines.append(issue.description[:4000])
    return "\n".join(lines).strip()


def format_workspace_digest(issues: list[LinearIssue]) -> str:
    lines = ["# Linear workspace sync", "", f"Synced {len(issues)} issues.", ""]
    for issue in issues[:120]:
        assignee = issue.assignee_name or "unassigned"
        lines.append(
            f"- **{issue.identifier}** [{issue.state_name}] {issue.title} — {assignee}"
        )
    if len(issues) > 120:
        lines.append(f"- … and {len(issues) - 120} more")
    return "\n".join(lines).strip()


def seat_email_index(access_store: AccessStore) -> dict[str, str]:
    """Map assignee email (lowercase) → seat node dataset ``seat:{slug}``."""
    mapping: dict[str, str] = {}
    for principal in access_store.snapshot().get("principals", []):
        if not isinstance(principal, dict):
            continue
        slug = principal.get("seat_slug")
        email = principal.get("email")
        if slug and email:
            mapping[str(email).strip().lower()] = seat_dataset(str(slug))
    return mapping


def resolve_mirror_dataset(
    issue: LinearIssue,
    email_index: dict[str, str],
    *,
    linear_user_map: dict[str, str] | None = None,
) -> str | None:
    if issue.assignee_email and issue.assignee_email in email_index:
        return email_index[issue.assignee_email]
    if linear_user_map and issue.assignee_id and issue.assignee_id in linear_user_map:
        slug = linear_user_map[issue.assignee_id]
        return seat_dataset(slug)
    return None


class LinearSyncer:
    def __init__(
        self,
        citadel: Citadel,
        *,
        client: LinearClient | None = None,
        access_store: AccessStore | None = None,
    ) -> None:
        self.citadel = citadel
        self.config = citadel.config
        self.client = client
        self.access_store = access_store
        self.state_path = Path(_linear_state_path(self.config.linear_sync_state_path))

    def _client(self) -> LinearClient:
        if self.client:
            return self.client
        api_key = self.config.linear_api_key
        if not api_key:
            raise LinearAPIError("CITADEL_LINEAR_API_KEY is not configured")
        return LinearClient(api_key=api_key)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": STATE_VERSION, "issues": [], "mirrors": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": STATE_VERSION, "issues": [], "mirrors": {}}
        return payload if isinstance(payload, dict) else {"version": STATE_VERSION, "issues": [], "mirrors": {}}

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def status(self) -> dict[str, Any]:
        state = self._load_state()
        issues = state.get("issues") if isinstance(state.get("issues"), list) else []
        mirrors = state.get("mirrors") if isinstance(state.get("mirrors"), dict) else {}
        mirror_count = sum(len(v) for v in mirrors.values() if isinstance(v, list))
        return {
            "enabled": bool(self.config.linear_api_key),
            "dataset": self.config.linear_sync_dataset,
            "last_synced_at": state.get("last_synced_at"),
            "issue_count": len(issues),
            "mirror_count": mirror_count,
            "state_path": str(self.state_path),
        }

    def issues_for_scope(
        self,
        *,
        scope: str,
        seat_dataset_name: str | None,
    ) -> list[dict[str, Any]]:
        state = self._load_state()
        issues = state.get("issues") if isinstance(state.get("issues"), list) else []
        if scope == "org":
            return [item for item in issues if isinstance(item, dict)]
        if scope == "my" and seat_dataset_name:
            mirrors = state.get("mirrors") if isinstance(state.get("mirrors"), dict) else {}
            ids = mirrors.get(seat_dataset_name)
            if not isinstance(ids, list):
                return []
            wanted = {str(item) for item in ids}
            return [
                item
                for item in issues
                if isinstance(item, dict) and str(item.get("identifier")) in wanted
            ]
        return []

    async def run(self, *, force: bool = False) -> dict[str, Any]:
        if not self.config.linear_api_key:
            return {"ok": False, "enabled": False, "reason": "linear_api_key_missing"}

        client = self._client()
        issues = await asyncio.to_thread(
            client.fetch_issues,
            max_issues=self.config.linear_sync_max_issues,
        )
        email_index = (
            seat_email_index(self.access_store)
            if self.access_store
            else {}
        )
        user_map = self.config.linear_user_map

        learning = LearningProcess(self.citadel)
        central_dataset = self.config.linear_sync_dataset or CENTRAL_DATASET
        session_id = self.config.linear_sync_session

        digest = format_workspace_digest(issues)
        central_outcome = await learning.learn(
            digest,
            dataset=central_dataset,
            tags=["linear-workspace", "linear-sync"],
            session_id=session_id,
            operation="linear_sync",
            run_improve=self.config.linear_sync_run_improve,
            tier="full",
        )

        mirrored = 0
        mirrors: dict[str, list[str]] = {}
        for issue in issues:
            mirror_dataset = resolve_mirror_dataset(issue, email_index, linear_user_map=user_map)
            if not mirror_dataset:
                continue
            note = format_issue_note(issue)
            await learning.learn(
                note,
                dataset=mirror_dataset,
                tags=[
                    "linear-assignee",
                    "linear-issue",
                    f"linear:{issue.identifier}",
                    issue.team_key or "linear",
                ],
                session_id=f"linear-{mirror_dataset.removeprefix(SEAT_DATASET_PREFIX)}",
                operation="linear_mirror",
                run_improve=False,
                tier="light",
            )
            mirrors.setdefault(mirror_dataset, []).append(issue.identifier)
            mirrored += 1

        payload = {
            "version": STATE_VERSION,
            "last_synced_at": utc_now(),
            "issues": [asdict(issue) for issue in issues],
            "mirrors": mirrors,
        }
        self._save_state(payload)

        return {
            "ok": True,
            "enabled": True,
            "issue_count": len(issues),
            "mirrored_count": mirrored,
            "central_ingested": central_outcome.ingest.accepted,
            "mirrors": mirrors,
            "last_synced_at": payload["last_synced_at"],
        }
