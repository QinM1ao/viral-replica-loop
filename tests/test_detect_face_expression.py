import unittest

from tools import detect_face_expression


class DetectFaceExpressionTest(unittest.TestCase):
    def test_initial_closed_and_repeated_blinks_are_distinct_events(self):
        values = [
            (0.8, 0.8, 0.04, 0.04),
            (0.75, 0.74, 0.05, 0.05),
            (0.2, 0.2, 0.16, 0.16),
            (0.2, 0.2, 0.16, 0.16),
            (0.72, 0.70, 0.05, 0.05),
            (0.68, 0.67, 0.05, 0.05),
            (0.2, 0.2, 0.16, 0.16),
            (0.65, 0.62, 0.05, 0.05),
            (0.64, 0.61, 0.05, 0.05),
            (0.2, 0.2, 0.16, 0.16),
        ]
        frames = [
            {
                "frame": index,
                "time_seconds": index / 30,
                "blink_left": left,
                "blink_right": right,
                "ear_left": ear_left,
                "ear_right": ear_right,
            }
            for index, (left, right, ear_left, ear_right) in enumerate(values)
        ]

        detect_face_expression.classify_frames(
            frames,
            closed_threshold=0.5,
            open_threshold=0.38,
            closed_ear_max=0.1,
            open_ear_min=0.12,
        )
        events = detect_face_expression.closure_events(frames, min_closed_frames=2)

        self.assertEqual(
            [event["type"] for event in events],
            ["initial_closed_then_open", "blink", "blink"],
        )

    def test_open_eye_geometry_clears_side_pose_blendshape_bias(self):
        frames = [
            {
                "frame": 0,
                "time_seconds": 0.0,
                "blink_left": 0.52,
                "blink_right": 0.12,
                "ear_left": 0.25,
                "ear_right": 0.18,
            }
        ]

        detect_face_expression.classify_frames(
            frames,
            closed_threshold=0.5,
            open_threshold=0.38,
            closed_ear_max=0.1,
            open_ear_min=0.12,
        )

        self.assertEqual(frames[0]["eye_state"], "both_open")


if __name__ == "__main__":
    unittest.main()
