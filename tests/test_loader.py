from pixcull.io.formats import ALL_EXTS, RAW_EXTS, is_raw


def test_raw_extensions_subset_of_all():
    assert RAW_EXTS <= ALL_EXTS


def test_is_raw_true_for_cr3():
    assert is_raw(".CR3")
    assert is_raw("photo.cr3")


def test_is_raw_false_for_jpg():
    assert not is_raw(".jpg")
    assert not is_raw("photo.jpg")
