"""`citadel tui` — a live terminal dashboard for teammates without the web UI.

Thin presentation layer over ``kb.status.gather_status`` (the same checks that
back ``citadel status --json``). Requires the optional ``textual`` dependency
(`pip install 'citadel-archive[tui]'`); imported lazily so the base CLI stays light.
"""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from kb.status import _CHECK_LABELS, StatusReport, gather_status

_OK = "[green]✓[/]"
_BAD = "[red]✗[/]"


def _identity_markup(report: StatusReport) -> str:
    # Untrusted Node data (seat/role/node/detail) is escaped before interpolation
    # so a value containing Rich markup (e.g. a commit title "[WIP] fix") can
    # neither crash the render nor inject styling/clickable links.
    ident = report.identity
    seat = escape(str(ident.get("seat_slug") or ident.get("actor") or "—"))
    role = escape(str(ident.get("role") or "—"))
    node = escape(str(report.node_url))
    overall = "[green]connected[/]" if report.healthy else "[red]not connected[/]"
    return f"[b]Citadel[/]   seat: [b]{seat}[/]   role: {role}   {overall}\n[dim]{node}[/]"


def _checks_markup(report: StatusReport) -> str:
    lines = ["[b]Connection & setup[/]"]
    for check in report.checks:
        dot = _OK if check.ok else _BAD
        label = _CHECK_LABELS.get(check.name, check.name)
        latency = f"  [dim]({check.latency_ms}ms)[/]" if check.latency_ms is not None else ""
        lines.append(f"  {dot} {escape(label):<16} {escape(check.detail)}{latency}")
    return "\n".join(lines)


def _recent_markup(report: StatusReport) -> str:
    if not report.recent:
        return "[b]Recent activity[/]\n  [dim]none yet[/]"
    lines = ["[b]Recent activity[/]"]
    for item in report.recent[:8]:
        when = escape(str(item.get("created_at") or item.get("timestamp") or "")[:19])
        label = escape(str(item.get("title") or item.get("action") or item.get("detail") or "—"))
        lines.append(f"  [dim]{when}[/]  {label}")
    return "\n".join(lines)


class StatusApp(App):
    """Live-refreshing Citadel status dashboard."""

    TITLE = "Citadel"
    CSS = """
    Static { padding: 1 2; }
    #identity { background: $panel; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        node_url: str,
        token: str | None,
        *,
        repo: Path,
        config_path: Path | None,
        refresh_seconds: float = 15.0,
    ) -> None:
        super().__init__()
        self._node_url = node_url
        self._token = token
        self._repo = repo
        self._config_path = config_path
        self._refresh_seconds = refresh_seconds

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("[dim]loading…[/]", id="identity")
        yield Static("", id="checks")
        yield Static("", id="recent")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_status()
        if self._refresh_seconds:
            self.set_interval(self._refresh_seconds, self.refresh_status)

    def action_refresh(self) -> None:
        self.refresh_status()

    @work(thread=True, exclusive=True)
    def refresh_status(self) -> None:
        report = gather_status(
            self._node_url,
            self._token,
            repo=self._repo,
            config_path=self._config_path,
        )
        self.call_from_thread(self._render, report)

    def _render(self, report: StatusReport) -> None:
        self.query_one("#identity", Static).update(_identity_markup(report))
        self.query_one("#checks", Static).update(_checks_markup(report))
        self.query_one("#recent", Static).update(_recent_markup(report))


def run_tui(
    node_url: str,
    token: str | None,
    *,
    repo: Path,
    config_path: Path | None = None,
    refresh_seconds: float = 15.0,
) -> None:
    StatusApp(
        node_url, token, repo=repo, config_path=config_path, refresh_seconds=refresh_seconds
    ).run()
