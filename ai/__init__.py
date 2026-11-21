"""The AI layer: a small night-level detector, its versioned weights, and the eval that gates them.

Deliberately tiny (a logistic score over four features) so the testing ideas stay visible:
code around the model is tested like any code; the model's quality is measured on a labelled
set, per slice, and a new version ships only if it is not worse than the current one.
"""
