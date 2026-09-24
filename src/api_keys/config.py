from .domain import Provider

PROVIDER_PRECEDENCE = (Provider.ANTHROPIC, Provider.OPENAI)

DEFAULT_MODEL = {
    Provider.ANTHROPIC: "claude-sonnet-5",
    Provider.OPENAI: "gpt-5.4",
}
