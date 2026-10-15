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


def test_a_missing_column_is_reported_as_an_incomplete_schema_not_a_bad_request():
    import httpx
    from app import supa
    for code, msg in (("PGRST204", "Could not find the 'kind' column of 'remediations' in the schema cache"),
                      ("42703", "column remediations.kind does not exist")):
        e = supa._error(httpx.Response(400, json={"code": code, "message": msg}))
        assert e.status == 503 and "schema is incomplete" in e.message, (code, e.message)
