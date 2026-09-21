from types import SimpleNamespace

from pricecheck.ingest.download import filename_from


def resp(cd):
    return SimpleNamespace(headers={"content-disposition": cd} if cd else {})


def test_filename_from_disposition_star():
    r = resp("attachment;filename=\"a (1).json\";filename*=UTF-8''106010776_ucsf%20medical.json")
    assert filename_from(r, "https://x/y") == "106010776_ucsf medical.json"


def test_filename_from_plain_disposition():
    assert filename_from(resp('attachment; filename="x_standardcharges.zip"'), "https://x/y") == "x_standardcharges.zip"


def test_filename_from_url_and_sanitised():
    assert filename_from(resp(None), "https://h/dir/a%20b/../c$d.csv?q=1") == "c_d.csv"
