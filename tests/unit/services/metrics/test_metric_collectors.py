"""Netsession: optional services contribute metrics through collectors
registered on the app, so the metrics service does not import them."""

import inspect

from flask import Flask

from byceps.services.metrics import metrics_service
from byceps.services.metrics.models import Metric


def test_registered_collectors_are_collected():
    app = Flask(__name__)
    metrics_service.register_metric_collector(
        app, lambda: iter([Metric('extra_count', 3)])
    )

    with app.app_context():
        metrics = list(metrics_service._collect_registered_metrics())

    assert metrics == [Metric('extra_count', 3)]


def test_metrics_service_does_not_import_the_tournament_system():
    assert 'netsession_tourney' not in inspect.getsource(metrics_service)
