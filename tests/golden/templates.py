"""The templates of the golden set: the sample of the spec (a consent form) and two more."""

from typing import Any, Final

from formlens.templates.models import FieldType, TemplateField

CONSENT: Final = (
    TemplateField("pesel", FieldType.TEXT, description="PESEL number, 11 digits", required=True, pattern="^[0-9]{11}$"),
    TemplateField("data_od", FieldType.DATE, description="Date from which the consent applies", required=True),
    TemplateField("zgoda", FieldType.BOOLEAN, description="Whether the person agreed (TAK is true)", required=True),
    TemplateField("imie_nazwisko", FieldType.TEXT, description="First and last name of the person"),
    TemplateField("miasto", FieldType.TEXT, description="City of residence"),
)
INVOICE: Final = (
    TemplateField("numer_faktury", FieldType.TEXT, description="Invoice number after FAKTURA VAT nr", required=True),
    TemplateField("data_wystawienia", FieldType.DATE, description="Date of issue (not the payment due date)"),
    TemplateField("nabywca", FieldType.TEXT, description="Buyer (company name)"),
    TemplateField("kwota_brutto", FieldType.NUMBER, description="Gross total to pay", required=True, minimum=0),
    TemplateField("waluta", FieldType.CHOICE, description="Currency of the total", allowed_values=("PLN", "EUR")),
    TemplateField("zaplacono", FieldType.BOOLEAN, description="Whether the invoice is marked as paid"),
)
REQUEST: Final = (
    TemplateField("numer_wniosku", FieldType.TEXT, description="Number of the request", required=True),
    TemplateField("data_zlozenia", FieldType.DATE, description="Date the request was submitted"),
    TemplateField("liczba_osob", FieldType.INTEGER, description="Number of people", minimum=1),
    TemplateField(
        "rodzaj", FieldType.CHOICE, description="Kind of request", allowed_values=("urlop", "zwolnienie", "delegacja")
    ),
    TemplateField("uwagi", FieldType.TEXT, description="Remarks written by the applicant"),
)

TEMPLATES: Final = {"zgoda": CONSENT, "faktura": INVOICE, "wniosek": REQUEST}


def body_of(key: str) -> dict[str, Any]:
    """The request body that creates the template `key` through `POST /v1/templates`."""
    return {
        "name": key,
        "fields": [
            {
                "name": f.name,
                "type": f.type.value,
                "description": f.description,
                "required": f.required,
                **({"allowed_values": list(f.allowed_values)} if f.allowed_values else {}),
                **({"minimum": f.minimum} if f.minimum is not None else {}),
                **({"pattern": f.pattern} if f.pattern else {}),
            }
            for f in TEMPLATES[key]
        ],
    }
