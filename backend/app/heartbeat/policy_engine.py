from typing import Any, Dict, List
import structlog
import json # For safe evaluation

logger = structlog.get_logger("aether.heartbeat.policy_engine")

class PolicyEngine:
    """Evaluates YAML-based rules against probe results to determine severity and actions."""

    def __init__(self):
        self.rules = []
        logger.info("policy_engine.initialized")

    def load_rules(self, rules_config: List[Dict[str, Any]]):
        """Loads policy rules from a configuration list."""
        self.rules = rules_config
        logger.info("policy_engine.rules_loaded", count=len(self.rules))

    def evaluate(self, probe_results: Dict[str, Any]) -> Dict[str, Any]:
        """Matches probe results against rules, returns decisions."""
        evaluated_decision = {"severity": "ok", "action": None, "matched_rule": None}
        
        # Flatten probe results for easier evaluation (e.g., probes.court_roll_rss.status)
        flat_results = {}
        for probe_name, result in probe_results.items():
            for key, value in result.items():
                flat_results[f"probes.{probe_name}.{key}"] = value
        
        # Sort rules by priority if needed (e.g., critical first)
        # For now, process in order of definition
        
        for rule in self.rules:
            condition_str = rule.get("condition")
            action = rule.get("action")
            priority = rule.get("priority", "low")
            rule_name = rule.get("name", "unnamed_rule")

            if not condition_str:
                logger.warning("policy_engine.rule_missing_condition", rule_name=rule_name)
                continue

            try:
                # Safely evaluate the condition string
                # WARNING: Using eval() is dangerous. For production, a dedicated rule engine library
                # or a more sophisticated parser should be used to prevent arbitrary code execution.
                # For this guide, we'll use a simplified approach assuming trusted input.
                
                # Replace placeholders in condition string with actual values
                formatted_condition = condition_str
                for key, value in flat_results.items():
                    # Handle string values by quoting them in the condition
                    if isinstance(value, str):
                        formatted_condition = formatted_condition.replace(key, json.dumps(value))
                    else:
                        formatted_condition = formatted_condition.replace(key, str(value))
                
                # Basic check for common comparison operators to ensure it's an expression
                if any(op in formatted_condition for op in ['==', '!=', '>', '<', '>=', '<=']):
                    condition_met = eval(formatted_condition, {"__builtins__": {}}, flat_results)
                else:
                    condition_met = False # If no operator, assume not a valid condition for eval

                if condition_met:
                    evaluated_decision["severity"] = priority
                    evaluated_decision["action"] = action
                    evaluated_decision["matched_rule"] = rule_name
                    logger.info("policy_engine.rule_matched", rule_name=rule_name, condition=condition_str, flat_results=flat_results)
                    # For simplicity, stop on first match. More complex logic might aggregate.
                    break
            except Exception as e:
                logger.error("policy_engine.rule_evaluation_error", rule_name=rule_name, condition=condition_str, error=str(e))

        return evaluated_decision