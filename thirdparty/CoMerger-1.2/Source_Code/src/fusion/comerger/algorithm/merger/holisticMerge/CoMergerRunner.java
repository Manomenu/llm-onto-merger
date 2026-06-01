package fusion.comerger.algorithm.merger.holisticMerge;

import java.io.File;
import java.util.HashMap;

import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.io.RDFXMLOntologyFormat;

import fusion.comerger.algorithm.merger.holisticMerge.localTest.StatisticTest;
import fusion.comerger.algorithm.merger.model.HModel;

/**
 * Parametric CLI entry point for CoMerger's HolisticMerger.
 *
 * Mirrors {@link LocalRun_HolisticMerger#main(String[])} but reads paths from
 * argv instead of using hardcoded Windows paths.  Activates all default GMR
 * rules (the same set the original LocalRun used) and writes the merged
 * ontology to the requested target path in RDF/XML.
 *
 * Usage:
 *   java -cp <classpath> fusion.comerger.algorithm.merger.holisticMerge.CoMergerRunner \
 *       <ont1.owl> <ont2.owl> <alignment.rdf> <target.owl>
 */
public class CoMergerRunner {

    private static final String DEFAULT_RULES = String.join(",",
        "ClassCheck", "ProCheck", "InstanceCheck", "CorresCheck", "CorssPropCheck",
        "ValueCheck", "StrCheck", "ClRedCheck", "ProRedCheck", "InstRedCheck",
        "PathRedCheck", "ExtCheck", "DomRangMinCheck", "AcyClCheck", "AcyProCheck",
        "RecProCheck", "UnconnClCheck", "UnconnProCheck", "EntCheck", "TypeCheck",
        "ConstValCheck", "CardCheck"
    );

    public static void main(String[] args) throws Exception {
        if (args.length < 4 || args.length > 5) {
            System.err.println(
                "Usage: CoMergerRunner <ont1.owl> <ont2.owl> <alignment.rdf> <target.owl> [output_dir]"
            );
            System.err.println(
                "  output_dir: directory used by CoMerger internally (defaults to dirname(target.owl))"
            );
            System.exit(1);
        }

        String ont1 = new File(args[0]).getAbsolutePath();
        String ont2 = new File(args[1]).getAbsolutePath();
        String alignment = new File(args[2]).getAbsolutePath();
        File targetFile = new File(args[3]).getAbsoluteFile();
        File workDir;
        if (args.length == 5) {
            workDir = new File(args[4]).getAbsoluteFile();
        } else {
            workDir = targetFile.getParentFile();
        }
        if (workDir != null && !workDir.exists()) workDir.mkdirs();
        // CoMerger expects the path to end with a separator (it concatenates
        // filename directly to it).
        String workDirStr = workDir.getAbsolutePath() + File.separator;

        // ontList = ";"-separated absolute paths
        String ontList = ont1 + ";" + ont2;

        StatisticTest.result = new HashMap<String, String>();

        HolisticMerger merger = new HolisticMerger();
        HModel ontM = merger.run(
            ontList,
            alignment,
            workDirStr,
            DEFAULT_RULES,
            "equal",      // preferredOnt
            "RDFtype"     // outputType — RDF/XML
        );

        // CoMerger writes its result to workDir/MergedOnt<random_id>.owl.
        // Save under the explicit target name so downstream metrics can find
        // it reliably.
        OWLOntology merged = ontM.getOwlModel();
        if (merged == null) {
            throw new RuntimeException(
                "CoMerger returned an HModel without an OWLOntology — cannot save to " + targetFile
            );
        }
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        manager.saveOntology(merged, new RDFXMLOntologyFormat(), IRI.create(targetFile.toURI()));
        System.out.println("==> Saved merged ontology to: " + targetFile);

        // Clean up CoMerger's auto-generated MergedOnt<id>.owl if it differs
        // from our target — keep workDir tidy.
        String autoName = ontM.getOntName();
        if (autoName != null) {
            File auto = new File(autoName);
            if (auto.exists() && !auto.getAbsolutePath().equals(targetFile.getAbsolutePath())) {
                auto.delete();
            }
        }
    }
}
