from scout_perception.species_labels import NOT_PLANTS, OTHER_LIFE, SPECIES, reject_prompts


def test_rejects_do_not_name_a_listed_species():
    listed = {sci for _, _, sci in SPECIES}
    assert not listed & set(OTHER_LIFE)
    assert len(set(OTHER_LIFE)) == len(OTHER_LIFE)


def test_reject_prompts_cover_both_lists():
    prompts = reject_prompts()
    assert prompts[:len(NOT_PLANTS)] == NOT_PLANTS
    assert len(prompts) == len(NOT_PLANTS) + len(OTHER_LIFE)
    assert 'a photo of Homo sapiens' in prompts
