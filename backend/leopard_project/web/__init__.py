"""Phase 2A-0 local research Web MVP."""

__all__ = ["create_app"]


def __getattr__(name: str):
    # Keep package import lightweight so Provider persistence can reference the
    # declarative models without recursively constructing the FastAPI app.
    if name == "create_app":
        from .app import create_app
        return create_app
    raise AttributeError(name)
