from .alignment import AlignmentModule
from .amk_alignment import AmkAlignmentModule

alignment_modules_dict: dict[str, type[AlignmentModule]] = {
    "aml": AmkAlignmentModule,
}
