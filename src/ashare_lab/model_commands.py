"""Register governed model research commands on one Typer application."""

import typer

from ashare_lab.model_attribution_cli import model_attribute
from ashare_lab.model_evaluation_cli import model_evaluate
from ashare_lab.model_protocol_cli import model_preregister
from ashare_lab.portfolio_protocol_cli import portfolio_preregister
from ashare_lab.portfolio_veto_cli import portfolio_veto_targets
from ashare_lab.rank_training_cli import train_ridge_rank


def register_model_commands(app: typer.Typer) -> None:
    """Attach model commands without adding behavior to the root CLI."""
    app.command("model-attribute")(model_attribute)
    app.command("model-evaluate")(model_evaluate)
    app.command("model-preregister")(model_preregister)
    app.command("portfolio-preregister")(portfolio_preregister)
    app.command("portfolio-veto-targets")(portfolio_veto_targets)
    app.command("train-ridge-rank")(train_ridge_rank)
