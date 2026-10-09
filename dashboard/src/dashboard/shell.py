"""Estructura de la app: aviso fijo, acceso, barra lateral y cabecera de página.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La lógica de cada callback está en una función pura (`auth_step`, `visibility`, `page_title`,
`nav_state`, `toggle_menu_class`, `run_info`); los decoradores solo conectan componentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import dash
from dash import Input, Output, State, callback, ctx, dcc, html
from dash.development.base_component import Component
from shared.disclaimer import DISCLAIMER

from dashboard import fmt, runtime
from dashboard.api_client import ApiClient, ApiError
from dashboard.components.attrs import aria
from dashboard.session import Session, attempt_login, from_store

NAV: tuple[tuple[str, str, str], ...] = (
    ("resumen", "/", "Resumen"),
    ("lista", "/lista", "Lista"),
    ("programacion", "/programacion", "Programación"),
    ("simulacion", "/simulacion", "Simulación"),
    ("equidad", "/equidad", "Equidad"),
)
TITLES = {
    "/": "Resumen de la lista de espera",
    "/lista": "Lista priorizada",
    "/programacion": "Programación",
    "/simulacion": "Simulación de políticas",
    "/equidad": "Equidad entre grupos",
}
HIDDEN = {"display": "none"}
SHOWN: dict[str, str] = {}


# ------------------------------------------------------------------ funciones puras


@dataclass(frozen=True)
class AuthStep:
    """Qué hacer tras pulsar Entrar o Salir."""

    # La sesión lleva la clave de API: fuera del repr para que nunca llegue a un log.
    session: dict[str, str] | None = field(repr=False)
    error: str | None
    clear_key: bool
    changed: bool


def auth_step(trigger: str | None, client: ApiClient, api_key: str | None) -> AuthStep:
    """Entrar valida la clave con `GET /v1/me`; Salir borra la sesión y la caché."""
    if trigger == "logout-btn":
        client.clear_cache()
        return AuthStep(None, None, clear_key=True, changed=True)
    result = attempt_login(client, api_key)
    if result.session is None:
        return AuthStep(None, result.error, clear_key=False, changed=False)
    return AuthStep(result.session.to_store(), None, clear_key=True, changed=True)


def visibility(session_data: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Estilos de (pantalla de acceso, estructura): se muestra una u otra según la sesión."""
    if from_store(session_data) is None:
        return SHOWN, HIDDEN
    return HIDDEN, SHOWN


def page_title(pathname: str | None) -> str:
    """Título de página para la ruta."""
    return TITLES.get((pathname or "/").rstrip("/") or "/", "Prioriza")


def nav_state(pathname: str | None) -> list[tuple[str, list[Component | str]]]:
    """(clase CSS, contenido) de cada enlace según la ruta activa.

    El activo lleva la barra izquierda y, para lectores de pantalla, el texto "(página actual)".
    """
    current = (pathname or "/").rstrip("/") or "/"
    out: list[tuple[str, list[Component | str]]] = []
    for _, href, label in NAV:
        if current == href:
            out.append(
                (
                    "nav-link nav-link--active",
                    [label, html.Span(" (página actual)", className="sr-only")],
                )
            )
        else:
            out.append(("nav-link", [label]))
    return out


def toggle_menu_class(current: str | None) -> str:
    """Abre o cierra el menú desplegable de pantallas angostas."""
    return "sidebar" if current and "sidebar--open" in current else "sidebar sidebar--open"


def user_text(session_data: Any) -> str:
    """`usuario, rol` de la cabecera."""
    session = from_store(session_data)
    return f"{session.user}, {session.role}" if session else ""


def run_info(summary: dict[str, Any] | None) -> list[Component | str]:
    """Corrida en uso: id corto, tamaño y fecha de corte."""
    if not summary:
        return ["Corrida sintética no disponible."]
    return [
        html.Strong(f"Corrida {fmt.short_id(summary.get('run_id'))}"),
        html.Br(),
        f"{fmt.num(summary.get('run_entries'))} entradas",
        html.Br(),
        f"Corte {fmt.date_es(summary.get('as_of'))}",
        html.Br(),
        "Datos sintéticos",
    ]


def fetch_run_info(client: ApiClient, session: Session) -> dict[str, Any] | None:
    """Resumen de la lista (con caché) para la barra lateral; `None` si la API falla."""
    try:
        return client.waitlist_summary(session.api_key)
    except ApiError:
        return None


# ------------------------------------------------------------------ componentes


def login_view() -> html.Div:
    """Pantalla de acceso: un campo "Clave de API" y el botón "Entrar"."""
    return html.Div(
        html.Div(
            [
                html.H1("Prioriza"),
                html.P(
                    "Panel de apoyo a la gestión de listas de espera. El sistema apoya, no "
                    "decide: cada plan requiere revisión humana."
                ),
                html.Div(
                    [
                        html.Label("Clave de API", htmlFor="login-key"),
                        dcc.Input(
                            id="login-key",
                            type="password",
                            value="",
                            n_submit=0,
                            autoComplete="off",
                            debounce=False,
                        ),
                        html.Div(id="login-error", className="field-error", role="alert"),
                    ],
                    className="field",
                ),
                html.Button("Entrar", id="login-btn", n_clicks=0, className="btn btn--primary"),
            ],
            className="stack",
        ),
        className="login-view",
        id="login-view",
    )


def sidebar_view() -> html.Aside:
    """Barra lateral: marca, navegación y corrida en uso."""
    return html.Aside(
        [
            html.Div("Prioriza", className="brand"),
            html.Button(
                "Menú",
                id="menu-toggle",
                n_clicks=0,
                className="btn btn--quiet menu-toggle",
                **aria({"aria-controls": "nav", "aria-expanded": "false"}),
            ),
            html.Nav(
                [
                    dcc.Link(label, href=href, id=f"nav-{key}", className="nav-link")
                    for key, href, label in NAV
                ],
                id="nav",
                className="nav",
                **aria({"aria-label": "Páginas"}),
            ),
            html.Div(id="run-info", className="run-info"),
        ],
        id="sidebar",
        className="sidebar",
    )


def shell_view() -> list[Component]:
    """Barra lateral, cabecera con usuario y contenido de la página."""
    return [
        sidebar_view(),
        html.Div(
            [
                html.Header(
                    [
                        html.H1(id="page-title"),
                        html.Div(
                            [
                                html.Span(id="user-text"),
                                html.Button(
                                    "Salir", id="logout-btn", n_clicks=0, className="btn btn--quiet"
                                ),
                            ],
                            className="user-box",
                        ),
                    ],
                    className="page-header",
                ),
                html.Main(dash.page_container, id="main", className="content", tabIndex=-1),
            ],
            className="main-col",
        ),
    ]


def root_layout() -> html.Div:
    """Layout raíz: sesión, aviso permanente, acceso y estructura."""
    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="session", storage_type="session"),
            html.A("Saltar al contenido", href="#main", className="skip-link"),
            html.Div(DISCLAIMER, className="disclaimer-strip", role="note", id="disclaimer"),
            html.Div(login_view(), id="login-wrap"),
            html.Div(shell_view(), id="shell", className="shell", style=HIDDEN),
        ]
    )


# ------------------------------------------------------------------ callbacks


@callback(
    Output("session", "data"),
    Output("login-error", "children"),
    Output("login-key", "value"),
    Input("login-btn", "n_clicks"),
    Input("login-key", "n_submit"),
    Input("logout-btn", "n_clicks"),
    State("login-key", "value"),
    State("session", "data"),
    prevent_initial_call=True,
)
def on_auth(
    _clicks: int, _submit: int, _logout: int, api_key: str | None, session: Any
) -> tuple[Any, Any, Any]:
    """Entrar o Salir; la clave solo se guarda en el store de la sesión del navegador."""
    step = auth_step(ctx.triggered_id, runtime.get_client(), api_key)
    if step.error is not None:
        return dash.no_update, step.error, dash.no_update
    return step.session, "", "" if step.clear_key else dash.no_update


@callback(
    Output("login-wrap", "style"),
    Output("shell", "style"),
    Input("session", "data"),
)
def on_session_visibility(session: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Muestra el acceso o la estructura según haya sesión."""
    return visibility(session)


@callback(
    Output("page-title", "children"),
    Output("user-text", "children"),
    Input("url", "pathname"),
    Input("session", "data"),
)
def on_header(pathname: str | None, session: Any) -> tuple[str, str]:
    """Título de la página y usuario con su rol."""
    return page_title(pathname), user_text(session)


@callback(
    *[Output(f"nav-{key}", "className") for key, _, _ in NAV],
    *[Output(f"nav-{key}", "children") for key, _, _ in NAV],
    Input("url", "pathname"),
)
def on_nav(pathname: str | None) -> list[Any]:
    """Resalta la página activa (barra izquierda y texto para lectores de pantalla)."""
    states = nav_state(pathname)
    return [cls for cls, _ in states] + [content for _, content in states]


@callback(
    Output("sidebar", "className"),
    Output("menu-toggle", "aria-expanded"),
    Input("menu-toggle", "n_clicks"),
    State("sidebar", "className"),
    prevent_initial_call=True,
)
def on_menu_toggle(_clicks: int, current: str | None) -> tuple[str, str]:
    """Despliega o recoge el menú en pantallas angostas."""
    new = toggle_menu_class(current)
    return new, "true" if "sidebar--open" in new else "false"


@callback(Output("run-info", "children"), Input("session", "data"))
def on_run_info(session_data: Any) -> list[Component | str]:
    """Corrida sintética en uso."""
    session = from_store(session_data)
    if session is None:
        return []
    return run_info(fetch_run_info(runtime.get_client(), session))
