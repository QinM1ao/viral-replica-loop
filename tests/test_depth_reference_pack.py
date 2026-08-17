import unittest

from tools import depth_reference_pack as depth


class DepthReferencePackTest(unittest.TestCase):
    def test_portrait_output_uses_720p_dimensions_and_source_ratio(self):
        width, height = depth.target_dimensions(720, 1280)
        self.assertEqual((width, height), (720, 1280))
        self.assertLess(abs((width / height) - (720 / 1280)), 0.002)

    def test_landscape_output_uses_720p_long_edge_and_source_ratio(self):
        width, height = depth.target_dimensions(1920, 1080)
        self.assertEqual((width, height), (1280, 720))
        self.assertLess(abs((width / height) - (1920 / 1080)), 0.01)

    def test_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            depth.target_dimensions(0, 1080)


if __name__ == "__main__":
    unittest.main()
