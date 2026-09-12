"""Shared serialization helper for model dataclasses."""


def model_to_dict(instance, *, include_computed: bool = True) -> dict:
    from xping.exporters.serialize import to_dict
    return to_dict(instance, include_computed=include_computed)
