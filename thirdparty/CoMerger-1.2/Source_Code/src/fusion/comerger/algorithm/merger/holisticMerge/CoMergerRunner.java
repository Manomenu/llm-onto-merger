package fusion.comerger.algorithm.merger.holisticMerge;

import java.io.File;
import java.io.FileWriter;
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

        // Write sidecar JSON with CoMerger's authoritative counts + diagnostics.
        //
        // applied_equiv_*           : from HModel.getEqClasses() etc. — what CoMerger
        //                             actually collapsed (HMerging.equalProcess result).
        // input_corresponding_*     : from StatisticTest (HMapping after parsing
        //                             alignment file — only counts MATCHED URI).
        // output_equiv_class_axioms : count of owl:equivalentClass in the saved OWL
        //                             (NB: may differ from applied_equiv_classes!).
        // signature_*               : sizes of MergedModel signature — useful to
        //                             diagnose URI-mismatch when applied count is 0.
        int eqClass   = ontM.getEqClasses()        != null ? ontM.getEqClasses().size()        : 0;
        int eqObjPro  = ontM.getEqObjProperties()  != null ? ontM.getEqObjProperties().size()  : 0;
        int eqDataPro = ontM.getEqDataProperties() != null ? ontM.getEqDataProperties().size() : 0;
        String corrCls = StatisticTest.result.getOrDefault("corresponding_Class", "0");
        String corrObj = StatisticTest.result.getOrDefault("corresponding_object_properties", "0");
        String corrDat = StatisticTest.result.getOrDefault("corresponding_data_properties", "0");

        int sigClasses  = merged.getClassesInSignature().size();
        int sigObjProps = merged.getObjectPropertiesInSignature().size();
        int sigDatProps = merged.getDataPropertiesInSignature().size();
        int sigInds     = merged.getIndividualsInSignature().size();

        // Count owl:equivalentClass axioms in output (for comparison with applied_equiv_classes)
        int outputEquivClassAxioms = merged
            .getAxioms(org.semanticweb.owlapi.model.AxiomType.EQUIVALENT_CLASSES).size();
        int outputEquivObjPropAxioms = merged
            .getAxioms(org.semanticweb.owlapi.model.AxiomType.EQUIVALENT_OBJECT_PROPERTIES).size();
        int outputEquivDatPropAxioms = merged
            .getAxioms(org.semanticweb.owlapi.model.AxiomType.EQUIVALENT_DATA_PROPERTIES).size();

        File statsFile = new File(workDir, "comerger_stats.json");
        try (FileWriter w = new FileWriter(statsFile)) {
            w.write("{\n");
            w.write("  \"applied_equiv_classes\": "         + eqClass + ",\n");
            w.write("  \"applied_equiv_object_properties\": " + eqObjPro + ",\n");
            w.write("  \"applied_equiv_data_properties\": "   + eqDataPro + ",\n");
            w.write("  \"applied_equiv_total\": "             + (eqClass + eqObjPro + eqDataPro) + ",\n");
            w.write("  \"input_corresponding_classes\": "        + corrCls + ",\n");
            w.write("  \"input_corresponding_object_properties\": " + corrObj + ",\n");
            w.write("  \"input_corresponding_data_properties\": "   + corrDat + ",\n");
            w.write("  \"output_equiv_class_axioms\": "         + outputEquivClassAxioms + ",\n");
            w.write("  \"output_equiv_object_property_axioms\": " + outputEquivObjPropAxioms + ",\n");
            w.write("  \"output_equiv_data_property_axioms\": "   + outputEquivDatPropAxioms + ",\n");
            w.write("  \"signature_classes\": "           + sigClasses + ",\n");
            w.write("  \"signature_object_properties\": " + sigObjProps + ",\n");
            w.write("  \"signature_data_properties\": "   + sigDatProps + ",\n");
            w.write("  \"signature_individuals\": "       + sigInds + "\n");
            w.write("}\n");
        }
        System.out.println("==> Sidecar:  " + statsFile);
        System.out.println("    applied (collapsed equiv groups): classes=" + eqClass
            + " objpro=" + eqObjPro + " datapro=" + eqDataPro
            + " | total=" + (eqClass + eqObjPro + eqDataPro));
        System.out.println("    input (parsed from alignment):     classes=" + corrCls
            + " objpro=" + corrObj + " datapro=" + corrDat);
        System.out.println("    output OWL equiv axioms:           classes=" + outputEquivClassAxioms
            + " objpro=" + outputEquivObjPropAxioms + " datapro=" + outputEquivDatPropAxioms);
        if ((eqClass + eqObjPro + eqDataPro) == 0
            && (Integer.parseInt(corrCls) + Integer.parseInt(corrObj) + Integer.parseInt(corrDat)) == 0) {
            System.err.println(
                "==> WARNING: BOTH applied and input alignment counts are ZERO!\n"
                + "    Possible causes:\n"
                + "      - URIs in alignment file don't match URIs in source ontologies\n"
                + "        (CoMerger silently drops alignments where containsClassInSignature is false)\n"
                + "      - Source ontologies use different base IRI / namespace than what AML/LogMap\n"
                + "        emitted into the alignment .rdf\n"
                + "      - Alignment file format problem (expected OAEI RDF/XML)\n"
                + "    Diagnostic: MergedModel signature has "
                + sigClasses + " classes, " + sigObjProps + " object props, "
                + sigDatProps + " data props — should be > 0 if HBuilder loaded sources OK."
            );
        }

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
