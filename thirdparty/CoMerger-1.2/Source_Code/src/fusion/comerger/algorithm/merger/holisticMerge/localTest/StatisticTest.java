package fusion.comerger.algorithm.merger.holisticMerge.localTest;

import java.util.HashMap;

// Lightweight stub replacing the original StatisticTest, which depended on
// classes from excluded packages (evaluator/HEvaluator, servlets/MatchingProcess)
// plus a missing GenerateOutput class.  HolisticMerger and HBuilder only use
// the static `result` HashMap — this minimal version covers that.
public class StatisticTest {
    public static HashMap<String, String> result = new HashMap<>();
}
