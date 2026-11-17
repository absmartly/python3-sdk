import typing


class Holdout:
    """One entry of ``ContextData.holdouts``.

    The collector sends holdouts as plain objects, which the default
    deserializer keeps as dicts; the context accepts either form (any
    ``Mapping`` or an object with these attributes). An entry without a
    non-empty ``split`` is ignored. ``unitType`` and ``holdoutType`` are
    informational: a holdout is evaluated with the covered experiment's unit
    type, and its arm count comes from ``len(split)``.
    """
    id: typing.Optional[int] = 0
    name: typing.Optional[str] = None
    unitType: typing.Optional[str] = None
    iteration: typing.Optional[int] = 0
    seedHi: typing.Optional[int] = 0
    seedLo: typing.Optional[int] = 0
    split: typing.Optional[list[float]] = None
    holdoutType: typing.Optional[str] = None
