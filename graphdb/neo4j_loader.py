import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

class Neo4jLoader:
    def __init__(self):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def clear_database(self):
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("🧹 Database cleared.")

    def load_domain_knowledge(self):
        """
        Loads the enhanced Knowledge Graph based on Lam 9600 Etch papers.
        """
        cypher_query = """
        // 1. Equipment & Process Layer
        CREATE (eq:Equipment {name: "Lam 9600 Metal Etcher", vendor: "Lam Research"})
        CREATE (p:Process {name: "Al-stack Etch", type: "Metal Etching"})
        CREATE (step1:ProcessStep {name: "Plasma Etch"})
        CREATE (step2:ProcessStep {name: "Main Etch"})
        CREATE (step3:ProcessStep {name: "Over Etch"})
        
        CREATE (eq)-[:HAS_PROCESS]->(p)
        CREATE (p)-[:HAS_STEP]->(step1)
        CREATE (p)-[:HAS_STEP]->(step2)
        CREATE (p)-[:HAS_STEP]->(step3)

        // 2. Sensor Layer (Machine State Data)
        CREATE (sg1:SensorGroup {name: "Machine State Sensor"})
        CREATE (sg2:SensorGroup {name: "OES", full_name: "Optical Emission Spectroscopy"})
        CREATE (sg3:SensorGroup {name: "RFM", full_name: "RF Monitor"})

        UNWIND [
            {n: "BCl3 Flow", p: "Gas Flow"}, {n: "Cl2 Flow", p: "Gas Flow"},
            {n: "RF Bottom Power", p: "RF Power"}, {n: "RF Reflected Power", p: "RF Power"},
            {n: "Helium Pressure", p: "Pressure"}, {n: "Chamber Pressure", p: "Pressure"},
            {n: "TCP Top Power", p: "RF Power"}, {n: "TCP Reflected Power", p: "RF Power"},
            {n: "Vat Valve", p: "Valve Position"}, {n: "Endpoint A Detector", p: "Endpoint"}
        ] as s
        CREATE (sn:Sensor {name: s.n})
        CREATE (pm:Parameter {name: s.p})
        CREATE (sn)-[:MEASURES]->(pm)
        CREATE (p)-[:HAS_SENSOR]->(sn)
        CREATE (sg1)-[:CONTAINS]->(sn)

        // 3. Virtual Sensor & Wafer State Layer
        CREATE (vsm:VirtualSensorModel {name: "g model", type: "Predictive"})
        CREATE (ws1:WaferState {name: "Oxide Loss", unit: "nm"})
        CREATE (ws2:WaferState {name: "Line Width Reduction", unit: "nm"})
        CREATE (ws3:WaferState {name: "Etch Rate", unit: "A/min"})
        
        CREATE (sg1)-[:USED_BY]->(vsm)
        CREATE (sg2)-[:PROVIDES_REDUNDANT_ESTIMATE_OF]->(ws1)
        CREATE (sg3)-[:PROVIDES_REDUNDANT_ESTIMATE_OF]->(ws1)
        CREATE (vsm)-[:PREDICTS]->(ws1)
        CREATE (vsm)-[:PREDICTS]->(ws2)
        CREATE (vsm)-[:PREDICTS]->(ws3)

        // 4. Anomaly & Fault Layer
        CREATE (algo:Algorithm {name: "PCA", full_name: "Principal Component Analysis"})
        CREATE (task:Task {name: "MSPC", full_name: "Multivariate Statistical Process Control"})
        CREATE (f1:Fault {name: "Process Drift", type: "Continuous"})
        CREATE (f2:Fault {name: "TCP Top Pwr Fault", type: "Sensor Issue"})
        CREATE (f3:Fault {name: "Chamber Pressure Fault", type: "Pressure Issue"})
        CREATE (risk1:FaultRisk {name: "Over Etch Risk"})
        
        CREATE (algo)-[:USED_FOR]->(task)
        CREATE (task)-[:DETECTS]->(f1)
        CREATE (task)-[:DETECTS]->(f2)
        CREATE (task)-[:DETECTS]->(f3)
        CREATE (ws1)-[:INDICATES]->(risk1)

        // 5. Maintenance & Countermeasures Layer (Wet Strip PM)
        CREATE (symp1:FaultSymptom {name: "Particle Increase"})
        CREATE (symp2:FaultSymptom {name: "Pressure Deviation"})
        CREATE (cause1:Cause {name: "Process Induced Residue", source: "Chemical Reaction"})
        CREATE (cause2:Cause {name: "Deposition Buildup", source: "Sputtering"})
        
        CREATE (comp1:Component {name: "VAT Valve", material: "Aluminum"})
        CREATE (comp2:Component {name: "Chamber Lid", material: "Anodized Al"})
        CREATE (comp3:Component {name: "Manometer Port"})
        
        CREATE (sop1:SOP {
            title: "Wet Strip PM Procedure",
            steps: "1. DI Water Soak for chamber wall & VAT valve. 2. Scrub deposition using non-abrasive pads. 3. Manometer port cleaning. 4. Final IPA Wipe to prevent particle re-entry."
        })
        CREATE (sop2:SOP {
            title: "TCP Matcher Recalibration",
            steps: "1. Check RF cable connection. 2. Inspect capacitor state. 3. Recalibrate matcher tuning range."
        })

        CREATE (symp1)-[:POSSIBLE_CAUSE]->(cause2)
        CREATE (cause2)-[:AFFECTS_COMPONENT]->(comp1)
        CREATE (cause2)-[:AFFECTS_COMPONENT]->(comp2)
        CREATE (cause2)-[:RECOMMENDED_ACTION]->(sop1)
        CREATE (f2)-[:FIXED_BY]->(sop2)
        CREATE (f3)-[:FIXED_BY]->(sop1) // Pressure issues often need chamber cleaning

        // 6. Operation Sequence Layer
        CREATE (op1:OperationStep {name: "HGS-P2", description: "Main Chamber Shower Head Purge"})
        CREATE (op2:OperationStep {name: "HGS-P4", description: "Turbo Ramp-up & Pump Down"})
        CREATE (gas1:Gas {name: "N2", purpose: "Purge"})
        
        CREATE (op1)-[:USES_GAS]->(gas1)
        CREATE (op1)-[:PURGES]->(comp2)
        """
        with self.driver.session() as session:
            session.run(cypher_query)
            print("🚀 Deep Process Knowledge Graph loaded successfully.")

if __name__ == "__main__":
    loader = Neo4jLoader()
    try:
        loader.clear_database()
        loader.load_domain_knowledge()
    finally:
        loader.close()
