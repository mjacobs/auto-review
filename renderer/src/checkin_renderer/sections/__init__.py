"""Per-section renderers: pure functions rows -> markdown (or None to skip).

Section order is a literal list in compose.py. Each module here owns exactly
one section of the check-in note; sections whose producers haven't migrated
yet (vault, health) or whose views don't exist yet (projects) return None and
stay out of the renderer bracket until their phase lands.
"""
