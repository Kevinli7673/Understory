"""The plants BioCLIP chooses between. Edit this list to match what is in the habitat.

Each entry: (label shown to the user, invasive?, scientific name).
BioCLIP was trained on taxonomic names, so the scientific name does most of the work.
"""

SPECIES = [
    ('Brazilian pepper', True, 'Schinus terebinthifolia'),
    ('air potato', True, 'Dioscorea bulbifera'),
    ('cogongrass', True, 'Imperata cylindrica'),
    ('saw palmetto', False, 'Serenoa repens'),
    ('wild coffee', False, 'Psychotria nervosa'),
]

# Things that are not plants. If one of these wins, the crop is dropped instead of being forced
# into one of the species above.
NOT_PLANTS = ['a photo of a person', 'a photo of a hand', 'a photo of a wall', 'a photo of a ceiling',
              'a photo of a floor', 'a photo of furniture', 'a photo of a laptop', 'a photo of a robot']

# Other living things the camera meets indoors: people, pets, ornamental and house plants. BioCLIP knows taxa
# far better than phrases like "a photo of a person", so these catch what NOT_PLANTS misses. On Sat night the
# live system pinned a face as Brazilian pepper (0.93) and a purple flower garland as air potato (0.97); with
# this list those 11 crops score 0.52 or less and the five test photos still score 1.00.
OTHER_LIFE = ['Homo sapiens', 'Canis familiaris', 'Felis catus', 'Wisteria sinensis', 'Wisteria floribunda',
              'Lavandula angustifolia', 'Bougainvillea glabra', 'Epipremnum aureum', 'Ficus benjamina',
              'Dracaena trifasciata', 'Chlorophytum comosum', 'Phalaenopsis amabilis', 'Rosa chinensis',
              'Hydrangea macrophylla', 'Salix babylonica', 'Syringa vulgaris', 'Acer palmatum',
              'Monstera deliciosa', 'Quercus virginiana', 'Sabal palmetto']

EMBEDDING_SIZE = 512      # BioCLIP (ViT-B/16) image embedding length; the dashboard column is vector(512)


def prompt(label, scientific):
    return f'a photo of {scientific} with common name {label}'


def reject_prompts():
    """Everything a crop may look like instead of a listed species. If one of these wins, the crop is dropped."""
    return NOT_PLANTS + [f'a photo of {taxon}' for taxon in OTHER_LIFE]
