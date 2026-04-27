from .alignment import AlignmentModule
from .aml_alignment import AmlAlignmentModule

alignment_modules_dict: dict[str, type[AlignmentModule]] = {
    "aml": AmlAlignmentModule,
}
