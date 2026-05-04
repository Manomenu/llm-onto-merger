import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

from ..logger import get_logger
from .alignment import Alignment, AlignmentModule

log = get_logger(__name__)

ALIGNMENT_OUTPUT = Path("artifacts") / "tmp_alignment.owl"

_NS_ALIGN = "http://knowledgeweb.semanticweb.org/heterogeneity/alignment"
_NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


class AmlAlignmentModule(AlignmentModule):
    def __init__(
        self,
        jar_path: Path = Path("thirdparty/aml/AgreementMakerLight.jar"),
    ):
        self.jar_path = jar_path

    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> list[Alignment]:
        cmd = [
            "java",
            "-jar",
            str(self.jar_path),
            "-s",
            str(base_ontology_path),
            "-t",
            str(candidate_ontology_path),
            "-o",
            str(ALIGNMENT_OUTPUT),
            "-a",
        ]

        log.info("Running AML: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"AML failed with return code {process.returncode}.\n"
                f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )

        log.info("Alignment written to %s", ALIGNMENT_OUTPUT)

        return self._load_alignments(ALIGNMENT_OUTPUT)

    def _load_alignments(self, alignment_path: Path) -> list[Alignment]:
        """Parse an EDOAL alignment file and return all alignment cells."""
        tree = ET.parse(alignment_path)
        root = tree.getroot()

        alignment_el = root.find(f"{{{_NS_ALIGN}}}Alignment")
        if alignment_el is None:
            raise ValueError(f"No <Alignment> element found in {alignment_path}")

        alignments: list[Alignment] = []
        for map_el in alignment_el.findall(f"{{{_NS_ALIGN}}}map"):
            cell = map_el.find(f"{{{_NS_ALIGN}}}Cell")
            if cell is None:
                continue
            alignments.append(
                Alignment(
                    entity1=cell.find(f"{{{_NS_ALIGN}}}entity1").get(
                        f"{{{_NS_RDF}}}resource"
                    ),
                    entity2=cell.find(f"{{{_NS_ALIGN}}}entity2").get(
                        f"{{{_NS_RDF}}}resource"
                    ),
                    measure=float(cell.findtext(f"{{{_NS_ALIGN}}}measure")),
                    relation=cell.findtext(f"{{{_NS_ALIGN}}}relation"),
                )
            )

        log.info("Loaded %d alignments from %s", len(alignments), alignment_path)
        return alignments
