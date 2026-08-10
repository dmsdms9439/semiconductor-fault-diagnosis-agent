import shap
import numpy as np
import pandas as pd
import json
import os

class SHAPExplainer:
    def __init__(self, lgb_model, features, stats_path='models/sensor_stats.json'):
        self.explainer = shap.TreeExplainer(lgb_model)
        self.features = [f.strip() for f in features]
        self.stats = {}
        if os.path.exists(stats_path):
            with open(stats_path, 'r') as f:
                raw_stats = json.load(f)
                self.stats = {k.strip(): v for k, v in raw_stats.items()}
        else:
            print(f"⚠️ Warning: {stats_path} not found. Normal ranges will be unavailable.")
        
    def explain(self, scaled_features, raw_features, pred_idx):
        """
        Explains the prediction and provides context using raw features and normal stats.
        Returns a structured JSON-ready dictionary.
        """
        shap_vals = self.explainer.shap_values(scaled_features)
        
        # Handle different SHAP output formats
        if isinstance(shap_vals, list):
            class_shap = shap_vals[pred_idx][0]
        else:
            if len(shap_vals.shape) == 3:
                class_shap = shap_vals[0, :, pred_idx]
            else:
                class_shap = shap_vals[0]
                
        # Get top 5 sensors (more context for GraphRAG)
        top_indices = np.argsort(np.abs(class_shap))[-5:][::-1]
        
        analysis_results = []
        for i in top_indices:
            sensor_name = self.features[i]
            shap_val = float(class_shap[i])
            current_val = float(raw_features.get(sensor_name, 0.0))
            
            # Context from stats
            stat = self.stats.get(sensor_name, {})
            mean = stat.get('mean', 0.0)
            u_bound = stat.get('upper_bound', 0.0)
            l_bound = stat.get('lower_bound', 0.0)
            
            # Determine status
            status = "Normal"
            if u_bound != 0.0 and current_val > u_bound:
                status = "High"
            elif l_bound != 0.0 and current_val < l_bound:
                status = "Low"
            
            # SHAP Direction
            direction = "Positive Influence" if shap_val > 0 else "Negative Influence"
            
            analysis_results.append({
                "sensor": sensor_name,
                "shap_value": shap_val,
                "current_value": round(current_val, 4),
                "mean_value": round(mean, 4),
                "normal_range": [round(l_bound, 4), round(u_bound, 4)],
                "status": status,
                "direction": direction
            })
            
        return analysis_results

if __name__ == "__main__":
    from inference import InferenceEngine
    engine = InferenceEngine()
    explainer = SHAPExplainer(engine.lgb_model, engine.features)
    
    test_df = pd.read_csv('data/test_split.csv')
    sample_row = test_df.iloc[0]
    sample_dict = sample_row.to_dict()
    result = engine.predict(sample_dict)
    
    # Simulation of anomaly
    pred_idx = 1 # Force an anomaly index for test
    analysis = explainer.explain(result['scaled_features'], sample_dict, pred_idx)
    print(json.dumps(analysis, indent=4))
