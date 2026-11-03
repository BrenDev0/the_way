import logging

import pytest

from src.core import log_noise


@pytest.fixture(autouse=True)
def restore_levels():
    saved = {name: logging.getLogger(name).level for name in log_noise.NOISY_LOGGERS}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


@pytest.mark.parametrize("name", log_noise.NOISY_LOGGERS)
def test_a_request_per_line_is_no_longer_logged_but_trouble_still_is(name, caplog):
    log_noise.quiet_http_clients()
    logger = logging.getLogger(name)

    with caplog.at_level(logging.INFO):
        logger.info('HTTP Request: GET https://queue.fal.run/x/status "HTTP/1.1 202 Accepted"')
        logger.warning("Connection pool is full")

    assert [record.getMessage() for record in caplog.records if record.name == name] == ["Connection pool is full"]


def test_other_loggers_are_left_as_they_are(caplog):
    log_noise.quiet_http_clients()

    with caplog.at_level(logging.INFO):
        logging.getLogger("src.background.jobs").info("task started")

    assert "task started" in caplog.text
