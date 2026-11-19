import pytest


def test_root_redirects_to_create(api):
    resp = api.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/create"


def test_create_page_has_form_from_mockup(api):
    html = api.get("/create").text
    for marker in ['id="name"', 'id="geo"', 'id="offer"', 'data-source="/api/offers"', ">Create</button>",
                   "jquery-3.7.1.min.js", "/static/create.js"]:
        assert marker in html


@pytest.mark.parametrize("path", ["/edit", "/edit/215534"])
def test_edit_page(api, path):
    resp = api.get(path)
    assert resp.status_code == 200
    assert "/static/edit.js" in resp.text
    assert 'data-source="/api/campaigns"' in resp.text


def test_edit_page_passes_campaign_id(api):
    assert 'data-campaign-id="215534"' in api.get("/edit/215534").text


@pytest.mark.parametrize("asset", ["app.css", "app.js", "create.js", "edit.js"])
def test_static_assets_served(api, asset):
    assert api.get(f"/static/{asset}").status_code == 200


def test_pages_not_in_openapi(api):
    paths = api.get("/openapi.json").json()["paths"]
    assert "/create" not in paths and "/edit" not in paths
