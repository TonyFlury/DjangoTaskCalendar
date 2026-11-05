"""Human-readable identities without exposing login names or email addresses."""


def user_display_name(user):
    """Use first and last names, with a neutral fallback for unresolved names."""
    return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or 'deleted user'
