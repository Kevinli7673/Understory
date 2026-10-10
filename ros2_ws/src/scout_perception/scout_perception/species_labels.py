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

EMBEDDING_SIZE = 512      # BioCLIP (ViT-B/16) image embedding length; the dashboard column is vector(512)


def prompt(label, scientific):
    return f'a photo of {scientific} with common name {label}'
