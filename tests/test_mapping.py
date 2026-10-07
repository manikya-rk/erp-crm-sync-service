import pytest
from sync.mapping import MappingError, erp_to_crm, normalise_phone, payload_hash
from tests.conftest import customer


def test_field_mapping():
    p = erp_to_crm(customer(1, SPERR=True, SMTP_ADDR="  A1@X.Example "))
    assert p["external_id"] == "1" and p["billing_state"] == "Karnataka" and p["billing_city"] == "Bengaluru"
    assert p["status"] == "On Hold" and p["email"] == "a1@x.example" and p["phone"] == "+91 98765 43210"


@pytest.mark.parametrize("raw,out", [("9876543210", "+91 98765 43210"), ("+91-98765-43210", "+91 98765 43210"),
                                     ("09876543210", "+91 98765 43210"), ("", None)])
def test_phone_normalisation(raw, out):
    assert normalise_phone(raw) == out


@pytest.mark.parametrize("over", [{"NAME1": "  "}, {"REGIO": "ZZ"}, {"SMTP_ADDR": "x@@y"}, {"TELF1": "12345"}])
def test_mapping_errors(over):
    with pytest.raises(MappingError):
        erp_to_crm(customer(1, **over))


def test_hash_is_stable_and_sensitive():
    a = erp_to_crm(customer(1))
    assert payload_hash(a) == payload_hash(dict(reversed(list(a.items()))))
    assert payload_hash(a) != payload_hash({**a, "credit_limit": 2000})
