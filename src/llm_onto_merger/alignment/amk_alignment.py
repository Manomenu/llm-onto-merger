import asyncio
from pathlib import Path

from ..logger import get_logger
from .alignment import AlignmentModule

log = get_logger(__name__)

ALIGNMENT_OUTPUT = Path("artifacts") / "tmp_alignment.owl"


class AmkAlignmentModule(AlignmentModule):
    def __init__(
        self,
        jar_path: Path = Path("thirdparty/amk/AgreementMakerLight.jar"),
    ):
        self.jar_path = jar_path

    async def create_alignment(
        self,
        base_ontology_path: Path,
        candidate_ontology_path: Path,
    ) -> None:
        cmd = [
            "java",
            "-jar",
            str(self.jar_path),
            "-s", str(base_ontology_path),
            "-t", str(candidate_ontology_path),
            "-o", str(ALIGNMENT_OUTPUT),
            "-a",
        ]

        log.info("Running AMK: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"AMK failed with return code {process.returncode}.\n"
                f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )

        log.info("Alignment written to %s", ALIGNMENT_OUTPUT)
