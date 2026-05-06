import pytest
import truststore

truststore.inject_into_ssl()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-eval",
        action="store_true",
        default=False,
        help="Run LLM-backed voice quality eval suite (slow, requires API key).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-eval"):
        return
    skip = pytest.mark.skip(reason="pass --run-eval to include the voice eval suite")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)
