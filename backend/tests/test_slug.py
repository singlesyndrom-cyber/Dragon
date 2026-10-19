from app.slug import normalize_tags, slugify


def test_slugify_translit_and_cleanup():
    assert slugify("Итоги турнира: EDH-пятница!") == "itogi-turnira-edh-pyatnitsa"
    assert slugify("Щука и Ёж") == "shchuka-i-ezh"
    assert slugify("!!!") == "post"
    assert len(slugify("а" * 200)) <= 80


def test_normalize_tags():
    assert normalize_tags([" #EDH ", "edh", "Берсерк", "", "  "]) == [("edh", "edh"), ("берсерк", "berserk")]
    assert len(normalize_tags([f"t{i}" for i in range(20)])) == 8
