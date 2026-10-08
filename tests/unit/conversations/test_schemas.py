import pytest

from src.conversations.schemas import ResolveToolCallsRequest, ResumeTurnRequest, SendMessageRequest


# The desktop app sends localFolder "" when no folder is open -- the prompt reads that as
# "none". The base model's two-character minimum turned every such message into a 422.
@pytest.mark.parametrize(
    "model, body",
    [
        (SendMessageRequest, {"message": "hola"}),
        (ResumeTurnRequest, {}),
        (ResolveToolCallsRequest, {"resolutions": []}),
    ],
)
def test_no_open_folder_is_accepted(model, body):
    request = model.model_validate({**body, "localFolder": "", "remoteFolder": ""})

    assert request.local_folder == ""
    assert request.remote_folder == ""
