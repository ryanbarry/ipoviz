"""Render a list of Series as an interactive Plotly chart."""

from __future__ import annotations

import plotly.graph_objects as go

from .data import Series


def label(s: Series) -> str:
    sym = s.requested if s.requested == s.symbol else f"{s.requested} → {s.symbol}"
    return f"{sym} (IPO {s.first_day:%Y-%m-%d})"


def build(series: list[Series], duration: str, relative: bool) -> go.Figure:
    fig = go.Figure()
    for s in series:
        close = s.prices["close"]
        y = (close / s.listing - 1) * 100 if relative else close
        fig.add_trace(
            go.Scatter(
                x=s.prices["day"],
                y=y,
                mode="lines+markers" if len(s.prices) < 30 else "lines",
                name=label(s),
                customdata=list(zip(s.prices["date"].dt.strftime("%Y-%m-%d"), close)),
                hovertemplate=(
                    f"<b>{s.symbol}</b> %{{customdata[0]}}<br>"
                    "day %{x}<br>"
                    + (f"%{{y:+.1f}}% vs ${s.listing:,.2f} open<br>$%{{customdata[1]:,.2f}}" if relative else "$%{y:,.2f}")
                    + "<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        title=f"First {duration} after IPO",
        xaxis_title="Calendar days since first trading day",
        yaxis_title="% change from first-day open" if relative else "Adjusted close (USD)",
        hovermode="closest",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    if relative:
        fig.update_yaxes(ticksuffix="%")
        fig.add_hline(y=0, line_width=1, line_color="gray")
    return fig
