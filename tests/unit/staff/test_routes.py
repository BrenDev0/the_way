from src.fastapi.main import app

WEB = "/api/v1"


def staff_surface() -> set[tuple[str, str]]:
    """Every (method, path) of the API that belongs to staff or to an owner invitation."""
    surface = set()
    for path, operations in app.openapi()["paths"].items():
        if path.startswith(f"{WEB}/staff") or path.startswith(f"{WEB}/owner-invitations"):
            surface |= {(method.upper(), path) for method in operations}
    return surface


def test_staff_can_sign_in_and_invite_owners_and_nothing_else():
    """Staff accounts are made by a command on the server and never changed from the API:
    there is no route to create one, change an email or a password, or list the staff.
    Adding any route here must be a decision, so it has to change this list."""
    assert staff_surface() == {
        ("POST", f"{WEB}/staff/auth/login"),
        ("POST", f"{WEB}/staff/auth/logout"),
        ("GET", f"{WEB}/staff/auth/me"),
        ("POST", f"{WEB}/staff/owner-invitations"),
        ("GET", f"{WEB}/staff/owner-invitations"),
        ("DELETE", f"{WEB}/staff/owner-invitations/{{invitation_id}}"),
        ("DELETE", f"{WEB}/staff/owner-invitations/{{invitation_id}}/record"),
        ("GET", f"{WEB}/staff/organizations"),
        ("GET", f"{WEB}/staff/organizations/{{organization_id}}"),
        ("DELETE", f"{WEB}/staff/organizations/{{organization_id}}"),
        ("GET", f"{WEB}/staff/organizations/{{organization_id}}/api-keys"),
        ("PUT", f"{WEB}/staff/organizations/{{organization_id}}/api-keys/{{provider}}"),
        ("DELETE", f"{WEB}/staff/organizations/{{organization_id}}/api-keys/{{provider}}"),
        ("POST", f"{WEB}/owner-invitations/accept"),
    }


def test_the_customers_cannot_register_themselves():
    paths = app.openapi()["paths"]

    assert not [path for path in paths if "register" in path]
