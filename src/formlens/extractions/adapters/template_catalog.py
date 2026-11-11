"""The extractions' view of the templates: ids in, a plain copy out."""

from uuid import UUID

from formlens.extractions.domain.exceptions import TemplateMissing
from formlens.extractions.domain.model import SnapshotField, TemplateSnapshot
from formlens.templates.exceptions import TemplateNotFound
from formlens.templates.json_schema import build_json_schema
from formlens.templates.service import TemplateService


class TemplateServiceCatalog:
    """Copies a template out of the templates module, so no template class crosses the boundary."""

    def __init__(self, service: TemplateService) -> None:
        """Use the templates service."""
        self._service = service

    def snapshot(self, template_id: UUID) -> TemplateSnapshot:
        """Return the template as it is now, as plain data."""
        try:
            template = self._service.get(template_id)
        except TemplateNotFound:
            raise TemplateMissing(template_id) from None
        return TemplateSnapshot(
            template_id=template.id,
            version=template.version,
            name=template.name,
            fields=tuple(
                SnapshotField(
                    name=item.name, type=item.type.value, description=item.description, required=item.required
                )
                for item in template.fields
            ),
            json_schema=build_json_schema(template.fields),
        )
