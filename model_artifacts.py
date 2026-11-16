"""Load trusted local sklearn artifacts only when their runtime is compatible."""
from __future__ import annotations

import warnings
from pathlib import Path


class ModelArtifactError(RuntimeError):
    pass


def load_sklearn_artifact(path: Path, models_dir: Path):
    """Raise on incompatible/corrupt artifacts; callers keep their rules fallback."""
    path = Path(path)
    try:
        path.resolve().relative_to(Path(models_dir).resolve())
    except ValueError as exc:
        raise ModelArtifactError("Путь модели выходит за каталог models.") from exc
    try:
        import joblib
        import sklearn
        from sklearn.exceptions import InconsistentVersionWarning
    except ImportError as exc:
        raise ModelArtifactError("Для обученного классификатора нужны scikit-learn и joblib.") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            artifact = joblib.load(path)
    except InconsistentVersionWarning as exc:
        original = getattr(exc, "original_sklearn_version", "неизвестна")
        current = getattr(exc, "current_sklearn_version", sklearn.__version__)
        raise ModelArtifactError(
            f"{path.name}: модель создана в scikit-learn {original}, "
            f"установлена версия {current}. Обученную модель отключили; "
            "для её использования требуется переобучение в текущем окружении."
        ) from exc
    except Exception as exc:
        raise ModelArtifactError(
            f"{path.name}: не удалось прочитать модель ({type(exc).__name__})."
        ) from exc
    # Future artifacts also record their runtime explicitly.
    version = artifact.get("sklearn_version") if isinstance(artifact, dict) else None
    if version and version != sklearn.__version__:
        raise ModelArtifactError(
            f"{path.name}: версия scikit-learn в метаданных {version}, "
            f"текущая {sklearn.__version__}. Требуется переобучение."
        )
    return artifact
