import httpx

from app import supa


def test_missing_postgrest_relation_has_migration_guidance():
    response = httpx.Response(404, json={
        "code": "PGRST205",
        "message": "Could not find the table 'public.conversations' in the schema cache",
    })

    error = supa._error(response)

    assert error.status == 503
    assert error.code == "PGRST205"
    assert "Apply the Supabase migrations" in error.message
