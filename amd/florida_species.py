"""A longer list of Central Florida plants for the deep pass's second opinion (`wide_top3`).

Same shape as scout_perception/species_labels.py: (common name, invasive?, scientific name).
"Invasive" here means listed as a Category I or II invasive by the Florida Invasive Species
Council. The five habitat species come first and keep the names the live system uses.

This list is only ever a second opinion. A pin's label always comes from the five-species list,
so that live pins, deep pins and the before/after count stay comparable.
"""

FLORIDA_SPECIES = [
    # the habitat list
    ('Brazilian pepper', True, 'Schinus terebinthifolia'),
    ('air potato', True, 'Dioscorea bulbifera'),
    ('cogongrass', True, 'Imperata cylindrica'),
    ('saw palmetto', False, 'Serenoa repens'),
    ('wild coffee', False, 'Psychotria nervosa'),
    # other invasives
    ('Old World climbing fern', True, 'Lygodium microphyllum'),
    ('melaleuca', True, 'Melaleuca quinquenervia'),
    ('Caesarweed', True, 'Urena lobata'),
    ('lantana', True, 'Lantana camara'),
    ('torpedograss', True, 'Panicum repens'),
    ('Chinese tallow', True, 'Triadica sebifera'),
    ('coral ardisia', True, 'Ardisia crenata'),
    ('camphor tree', True, 'Cinnamomum camphora'),
    ('tuberous sword fern', True, 'Nephrolepis cordifolia'),
    # other natives
    ('live oak', False, 'Quercus virginiana'),
    ('cabbage palm', False, 'Sabal palmetto'),
    ('slash pine', False, 'Pinus elliottii'),
    ('American beautyberry', False, 'Callicarpa americana'),
    ('gallberry', False, 'Ilex glabra'),
    ('wax myrtle', False, 'Morella cerifera'),
    ('wiregrass', False, 'Aristida stricta'),
    ('coontie', False, 'Zamia integrifolia'),
    ('muscadine grape', False, 'Vitis rotundifolia'),
    ('saw greenbrier', False, 'Smilax bona-nox'),
    ('bracken fern', False, 'Pteridium aquilinum'),
    ('Spanish moss', False, 'Tillandsia usneoides'),
]
