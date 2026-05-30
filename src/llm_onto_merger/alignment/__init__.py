from .alignment import AlignmentModule
from .aml_alignment import AmlAlignmentModule
from .logmap_alignment import LogmapAlignmentModule

alignment_modules_dict: dict[str, type[AlignmentModule]] = {
    "aml": AmlAlignmentModule,
    "logmap": LogmapAlignmentModule,
}
