"""
Neo4j Loader v2 — Paper-grounded Knowledge Graph for Lam 9600 Metal Etcher

Schema design references:
  - Wise et al. (1999) J. Chemom. 13, 379  : 19 MSS sensors, 21 fault catalog
  - Sofge (1997) NeuroDyne/SEMATECH J-88-E : f^-1, g virtual sensor models
  - Gallagher and Wise (1997) IFAC Safeprocess : EWMA/EWMC, 3 drift sources
  - Foamtec (2010) LAM 9600 Wet Strip PM : 43-step SOP, component map
  - Arpitha and Pani (2022) CABEQ 36(1) : FDC 4-stage taxonomy

Key improvements over v1:
  1. Causal chain is first-class: Sensor -> Symptom -> Cause -> Mechanism -> Component -> SOP
  2. SOP separated into abstract (cheap) and steps (expensive, fetched on demand)
  3. Each Fault carries a fingerprint (which sensors deviate, which direction)
     so SHAP top-k can be matched to faults via fingerprint similarity instead of name lookup
  4. Virtual sensor layer (Sofge) lets g-model wafer-state predictions feed FaultRisk
"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


class Neo4jLoaderV2:
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
            print("Database cleared.")

    def create_indexes(self):
        stmts = [
            "CREATE INDEX fault_name IF NOT EXISTS FOR (f:Fault) ON (f.name)",
            "CREATE INDEX sensor_name IF NOT EXISTS FOR (s:Sensor) ON (s.name)",
            "CREATE INDEX component_name IF NOT EXISTS FOR (c:Component) ON (c.name)",
            "CREATE INDEX sop_id IF NOT EXISTS FOR (sop:SOP) ON (sop.sop_id)",
        ]
        with self.driver.session() as session:
            for q in stmts:
                session.run(q)
        print("Indexes created.")

    # ------------------------------------------------------------------
    # L1 Equipment / Process (Wise 1999, Sofge 1997)
    # ------------------------------------------------------------------
    def load_equipment_layer(self, session):
        session.run("""
        MERGE (eq:Equipment {name:'Lam 9600 Metal Etcher'})
          SET eq.vendor='Lam Research',
              eq.process_class='Inductively Coupled Plasma',
              eq.reference='Wise 1999, J Chemom 13:379'
        MERGE (proc:Process {name:'Al-stack Etch'})
          SET proc.stack='TiN/Al-0.5%Cu/TiN/oxide', proc.chemistry='BCl3/Cl2'
        MERGE (eq)-[:RUNS]->(proc)

        FOREACH (r IN [
          {name:'Al etch',   step_order:1, step_role:'Main metal removal'},
          {name:'TiN etch',  step_order:2, step_role:'Barrier layer break-through'},
          {name:'Oxide etch',step_order:3, step_role:'Over-etch / endpoint margin'}
        ] |
          MERGE (s:ProcessStep {name:r.name})
            SET s.step_order=r.step_order, s.step_role=r.step_role
          MERGE (proc)-[:HAS_STEP]->(s)
        )

        FOREACH (p IN [
          'Pressure','TCP Top Power','RF Bottom Power',
          'BCl3 Flow','Cl2 Flow','Cl2/BCl3 Ratio','Total Flow'
        ] |
          MERGE (rp:RecipeParam {name:p})
          MERGE (proc)-[:HAS_RECIPE_PARAM]->(rp)
        )
        """)

    # ------------------------------------------------------------------
    # L2 Sensors (Wise 1999 Table 1, Sofge 1997 Fig 5)
    # ------------------------------------------------------------------
    def load_sensor_layer(self, session):
        mss_sensors = [
            ("BCl3 Flow",          "Gas Flow",  "MSS"),
            ("Cl2 Flow",           "Gas Flow",  "MSS"),
            ("RF Bottom Power",    "RF Power",  "MSS"),
            ("RFB Reflected Power","RF Power",  "MSS"),
            ("Endpoint A Detector","Endpoint",  "MSS"),
            ("Helium Pressure",    "Pressure",  "MSS"),
            ("Chamber Pressure",   "Pressure",  "MSS"),
            ("RF Tuner",           "RF Match",  "MSS"),
            ("RF Load",            "RF Match",  "MSS"),
            ("Phase Error",        "RF Match",  "MSS"),
            ("RF Power",           "RF Power",  "MSS"),
            ("RF Impedance",       "RF Match",  "MSS"),
            ("TCP Tuner",          "TCP Match", "MSS"),
            ("TCP Phase Error",    "TCP Match", "MSS"),
            ("TCP Impedance",      "TCP Match", "MSS"),
            ("TCP Top Power",      "RF Power",  "MSS"),
            ("TCP Reflected Power","RF Power",  "MSS"),
            ("TCP Load",           "TCP Match", "MSS"),
            ("Vat Valve",          "Valve",     "MSS"),
        ]
        session.run("""
        MERGE (sg1:SensorGroup {name:'MSS', full_name:'Machine State Sensor'})
          SET sg1.dim=19, sg1.reference='Wise 1999 Table 1'
        MERGE (sg2:SensorGroup {name:'OES', full_name:'Optical Emission Spectroscopy'})
          SET sg2.dim=43, sg2.range_nm='200-900', sg2.reference='Han 2008, Kim 2013'
        MERGE (sg3:SensorGroup {name:'RFM', full_name:'RF Monitor'})
          SET sg3.dim=70, sg3.harmonics=5, sg3.reference='Sofge 1997'
        """)
        for name, klass, group in mss_sensors:
            session.run("""
            MERGE (s:Sensor {name:$name})
              SET s.param_class=$klass, s.sensor_group=$group
            WITH s
            MATCH (sg:SensorGroup {name:$group})
            MERGE (sg)-[:CONTAINS]->(s)
            """, name=name, klass=klass, group=group)

        session.run("""
        MATCH (s:Sensor), (step:ProcessStep)
        MERGE (s)-[r:OBSERVED_AT]->(step)
          ON CREATE SET r.relevance = 1.0
        """)

    # ------------------------------------------------------------------
    # L3 Virtual Sensor Models (Sofge 1997)
    # ------------------------------------------------------------------
    def load_virtual_sensor_layer(self, session):
        session.run("""
        MERGE (finv:VirtualSensorModel {name:'f_inverse'})
          SET finv.purpose='Recipe setpoint verification',
              finv.method='Linear PLS preferred (Sofge 1997)',
              finv.reference='Sofge 1997 Sec 3.1'

        MERGE (gmod:VirtualSensorModel {name:'g_model'})
          SET gmod.purpose='Wafer-state prediction (LWR, Oxide Loss)',
              gmod.method='Linear PLS preferred',
              gmod.reference='Sofge 1997 Sec 3.2'

        MERGE (lwr:WaferState {name:'Line Width Reduction', unit:'micron', symbol:'LWR'})
        MERGE (ox:WaferState  {name:'Oxide Loss',            unit:'angstrom', symbol:'OL'})
        MERGE (er:WaferState  {name:'Etch Rate',             unit:'A/min',  symbol:'ER'})

        MERGE (gmod)-[:PREDICTS]->(lwr)
        MERGE (gmod)-[:PREDICTS]->(ox)
        MERGE (gmod)-[:PREDICTS]->(er)

        MERGE (r1:FaultRisk {name:'Over-etch Risk'})
        MERGE (r2:FaultRisk {name:'Under-etch Risk'})
        MERGE (r3:FaultRisk {name:'CD Out-of-Spec'})
        MERGE (ox)-[:INDICATES {threshold:'>1500A'}]->(r1)
        MERGE (er)-[:INDICATES {threshold:'<setpoint-10pct'}]->(r2)
        MERGE (lwr)-[:INDICATES {threshold:'>0.05um'}]->(r3)

        MERGE (mspc:MonitoringMethod {name:'EWMA-EWMC PCA'})
          SET mspc.alpha=0.1, mspc.beta=0.1,
              mspc.reference='Gallagher and Wise 1997 IFAC Safeprocess',
              mspc.statistics='Q (SPE), T2'
        MERGE (sg1:SensorGroup {name:'MSS'})
        MERGE (sg1)-[:MONITORED_BY]->(mspc)
        """)

    # ------------------------------------------------------------------
    # L4 Faults (Wise 1999 Table 2 — 21-fault catalog)
    # ------------------------------------------------------------------
    def load_fault_layer(self, session):
        # Fingerprint = which sensors deviate (low / high) for each fault.
        # SHAP top-k will be matched against this at inference time.
        faults = [
            ("F01","TCP+50",     "TCP Top Power",     [], ["TCP Top Power"], "all"),
            ("F02","RF-12",      "RF Bottom Power",   ["RF Bottom Power"], [], "all"),
            ("F03","RF+10",      "RF Bottom Power",   [], ["RF Bottom Power"], "all"),
            ("F04","Pr+3",       "Chamber Pressure",  [], ["Chamber Pressure","Vat Valve"], "all"),
            ("F05","TCP+10",     "TCP Top Power",     [], ["TCP Top Power"], "all"),
            ("F06","BCl3+5",     "BCl3 Flow",         [], ["BCl3 Flow"], "Al"),
            ("F07","Pr-2",       "Chamber Pressure",  ["Chamber Pressure"], [], "all"),
            ("F08","Cl2-5",      "Cl2 Flow",          ["Cl2 Flow"], [], "Al"),
            ("F09","He Chuck",   "Helium Pressure",   ["Helium Pressure"], [], "all"),
            ("F10","TCP+30",     "TCP Top Power",     [], ["TCP Top Power"], "all"),
            ("F11","Cl2+5",      "Cl2 Flow",          [], ["Cl2 Flow"], "Al"),
            ("F12","RF+8",       "RF Bottom Power",   [], ["RF Bottom Power"], "all"),
            ("F13","BCl3-5",     "BCl3 Flow",         ["BCl3 Flow"], [], "Al"),
            ("F14","Pr+2",       "Chamber Pressure",  [], ["Chamber Pressure"], "all"),
            ("F15","TCP-20",     "TCP Top Power",     ["TCP Top Power"], [], "all"),
            ("F16","TCP-15",     "TCP Top Power",     ["TCP Top Power"], [], "all"),
            ("F17","Cl2-10",     "Cl2 Flow",          ["Cl2 Flow"], [], "Al"),
            ("F18","RF-12 (v2)", "RF Bottom Power",   ["RF Bottom Power"], [], "all"),
            ("F19","BCl3+10",    "BCl3 Flow",         [], ["BCl3 Flow"], "Al"),
            ("F20","Pr+1",       "Chamber Pressure",  [], ["Chamber Pressure"], "all"),
            ("F21","TCP+20",     "TCP Top Power",     [], ["TCP Top Power"], "all"),
        ]
        for fid, name, induced, low_s, high_s, region in faults:
            session.run("""
            MERGE (f:Fault {fault_id:$fid})
              SET f.name=$name,
                  f.induced_via=$induced,
                  f.region=$region,
                  f.reference='Wise 1999 Table 2',
                  f.sensors_low=$low_s,
                  f.sensors_high=$high_s
            WITH f
            UNWIND $low_s AS s_name
              MATCH (s:Sensor {name:s_name})
              MERGE (s)-[:DEVIATES_LOW {fault_id:$fid}]->(f)
            """, fid=fid, name=name, induced=induced, region=region,
                 low_s=low_s, high_s=high_s)

            session.run("""
            MATCH (f:Fault {fault_id:$fid})
            UNWIND $high_s AS s_name
              MATCH (s:Sensor {name:s_name})
              MERGE (s)-[:DEVIATES_HIGH {fault_id:$fid}]->(f)
            """, fid=fid, high_s=high_s)

        # FaultCategory aggregation = coarse retrieval target (saves tokens).
        session.run("""
        MERGE (cat1:FaultCategory {name:'Pressure Disturbance'})
          SET cat1.recovery_priority=1, cat1.typical_lead_time_min=30
        MERGE (cat2:FaultCategory {name:'RF / TCP Power Drift'})
          SET cat2.recovery_priority=2, cat2.typical_lead_time_min=60
        MERGE (cat3:FaultCategory {name:'Gas Flow Imbalance'})
          SET cat3.recovery_priority=2, cat3.typical_lead_time_min=20
        MERGE (cat4:FaultCategory {name:'Wafer Chucking Failure'})
          SET cat4.recovery_priority=1, cat4.typical_lead_time_min=15
        """)
        session.run("""
        MATCH (f:Fault), (cat1:FaultCategory {name:'Pressure Disturbance'})
        WHERE f.induced_via = 'Chamber Pressure'
        MERGE (f)-[:BELONGS_TO]->(cat1)
        """)
        session.run("""
        MATCH (f:Fault), (cat2:FaultCategory {name:'RF / TCP Power Drift'})
        WHERE f.induced_via IN ['RF Bottom Power','TCP Top Power']
        MERGE (f)-[:BELONGS_TO]->(cat2)
        """)
        session.run("""
        MATCH (f:Fault), (cat3:FaultCategory {name:'Gas Flow Imbalance'})
        WHERE f.induced_via IN ['BCl3 Flow','Cl2 Flow']
        MERGE (f)-[:BELONGS_TO]->(cat3)
        """)
        session.run("""
        MATCH (f:Fault), (cat4:FaultCategory {name:'Wafer Chucking Failure'})
        WHERE f.induced_via = 'Helium Pressure'
        MERGE (f)-[:BELONGS_TO]->(cat4)
        """)

    # ------------------------------------------------------------------
    # L5 Cause / Mechanism / Component (Foamtec + Gallagher 1997)
    # ------------------------------------------------------------------
    def load_cause_layer(self, session):
        session.run("""
        MERGE (m1:Mechanism {name:'Residue Accumulation'})
          SET m1.timescale='1-2 months', m1.continuous=true,
              m1.reference='Gallagher 1997 Sec 4'
        MERGE (m2:Mechanism {name:'Sensor Drift'})
          SET m2.timescale='weeks', m2.continuous=true
        MERGE (m3:Mechanism {name:'Post-PM Reset Mismatch'})
          SET m3.timescale='instant', m3.continuous=false,
              m3.reference='Gallagher 1997 Sec 4'
        MERGE (m4:Mechanism {name:'He Backside Leak'})
          SET m4.timescale='instant', m4.continuous=false,
              m4.symptom='wafer dechucking, temperature uniformity loss'
        MERGE (m5:Mechanism {name:'Matcher Detune'})
          SET m5.timescale='days',
              m5.symptom='reflected power rise, impedance shift'
        MERGE (m6:Mechanism {name:'MFC Calibration Drift'})
          SET m6.timescale='weeks',
              m6.symptom='actual flow not equal setpoint, OES intensity shift'

        MERGE (c1:Component {name:'VAT Valve', material:'Aluminum'})
        MERGE (c2:Component {name:'Chamber Lid', material:'Anodized Al'})
        MERGE (c3:Component {name:'Manometer Port'})
        MERGE (c4:Component {name:'Slit Valve Door'})
        MERGE (c5:Component {name:'Electrostatic Chuck'})
        MERGE (c6:Component {name:'TCP Matcher'})
        MERGE (c7:Component {name:'RF Matcher'})
        MERGE (c8:Component {name:'BCl3 MFC'})
        MERGE (c9:Component {name:'Cl2 MFC'})
        MERGE (c10:Component {name:'O-ring Groove'})

        MERGE (m1)-[:DEGRADES]->(c1)
        MERGE (m1)-[:DEGRADES]->(c2)
        MERGE (m1)-[:DEGRADES]->(c3)
        MERGE (m4)-[:DEGRADES]->(c5)
        MERGE (m5)-[:DEGRADES]->(c6)
        MERGE (m5)-[:DEGRADES]->(c7)
        MERGE (m6)-[:DEGRADES]->(c8)
        MERGE (m6)-[:DEGRADES]->(c9)
        """)

        # Fault -> Mechanism causal hop. Done in separate calls so each
        # WITH/MATCH chain is unambiguous and Cypher-validates cleanly.
        session.run("""
        MATCH (f:Fault), (m:Mechanism {name:'Residue Accumulation'})
        WHERE f.induced_via='Chamber Pressure'
        MERGE (f)-[:CAUSED_BY {confidence:0.7}]->(m)
        """)
        session.run("""
        MATCH (f:Fault), (m:Mechanism {name:'He Backside Leak'})
        WHERE f.induced_via='Helium Pressure'
        MERGE (f)-[:CAUSED_BY {confidence:0.9}]->(m)
        """)
        session.run("""
        MATCH (f:Fault), (m:Mechanism {name:'Matcher Detune'})
        WHERE f.induced_via IN ['TCP Top Power','RF Bottom Power']
        MERGE (f)-[:CAUSED_BY {confidence:0.8}]->(m)
        """)
        session.run("""
        MATCH (f:Fault), (m:Mechanism {name:'MFC Calibration Drift'})
        WHERE f.induced_via IN ['BCl3 Flow','Cl2 Flow']
        MERGE (f)-[:CAUSED_BY {confidence:0.75}]->(m)
        """)

    # ------------------------------------------------------------------
    # L6 SOPs (Foamtec PM, vendor manuals) — separated abstract / steps
    # ------------------------------------------------------------------
    def load_sop_layer(self, session):
        sops = [
            {
                "sop_id": "SOP-WET-STRIP",
                "title": "Wet Strip Chamber PM",
                "abstract": "DI-water soak, 280-grit ScrubPAD, 800-grit polish, IPA wipe (4 phases, ~2 hr)",
                "tools": ["280-grit Diamond ScrubPAD","800-grit Diamond ScrubPAD","UltraSOLV Sponge","MiraWIPE","IPA"],
                "components": ["VAT Valve","Chamber Lid","Manometer Port","Slit Valve Door","O-ring Groove"],
                "reference": "Foamtec LAM 9600 Wet Strip PM Procedure (2010)",
                "steps": [
                    (1, "Vent and shut down chamber per safety guidelines"),
                    (2, "Reduce heater to 35-40 C"),
                    (3, "Remove slit valve doors, soak in DI water"),
                    (4, "Moisten chamber walls, VAT valve, lid with DI water"),
                    (5, "Soak chamber 1 hour"),
                    (6, "Pre-wipe with sponge to remove flakes"),
                    (9, "Scrub deposition with 280-grit ScrubPAD"),
                    (15,"Polish with 800-grit ScrubPAD"),
                    (21,"Clean VAT valve corners with 280-grit ScrubTIP"),
                    (27,"Polish O-ring grooves with 1350-grit ScrubTIP"),
                    (30,"Clean manometer ports with ScrubTIP and foam swab"),
                    (37,"Final IPA wipe with fresh MiraWIPE - critical for tool recovery"),
                    (42,"Final IPA wipe just before closing lid"),
                ],
            },
            {
                "sop_id": "SOP-TCP-RECAL",
                "title": "TCP Matcher Recalibration",
                "abstract": "Inspect RF cable, check matcher capacitor, recalibrate tuning range (~30 min)",
                "tools": ["RF impedance analyzer","Torque wrench"],
                "components": ["TCP Matcher"],
                "reference": "Wise 1999 + tool vendor manual",
                "steps": [
                    (1, "Verify RF cable connectors and torque to spec"),
                    (2, "Inspect matcher capacitor for arcing or pitting"),
                    (3, "Recalibrate tuning range against reference load"),
                    (4, "Run plasma ignition test, verify TCP Reflected Power below spec"),
                ],
            },
            {
                "sop_id": "SOP-RF-RECAL",
                "title": "RF Bottom Matcher Recalibration",
                "abstract": "Same procedure as TCP recal, applied to bottom RF source",
                "tools": ["RF impedance analyzer"],
                "components": ["RF Matcher"],
                "reference": "Tool vendor manual",
                "steps": [
                    (1, "Verify RF cable connectors"),
                    (2, "Recalibrate bottom RF matcher"),
                    (3, "Verify RFB Reflected Power below spec"),
                ],
            },
            {
                "sop_id": "SOP-MFC-CHECK",
                "title": "Mass Flow Controller Verification",
                "abstract": "Rate-of-rise test, compare actual vs setpoint, recalibrate or replace MFC",
                "tools": ["RoR fixture","N2 calibration gas"],
                "components": ["BCl3 MFC","Cl2 MFC"],
                "reference": "Standard MFC PM procedure",
                "steps": [
                    (1, "Isolate gas line, perform rate-of-rise (RoR) test"),
                    (2, "Compare actual flow against setpoint at 25/50/100 percent range"),
                    (3, "If error above 2 percent, recalibrate via vendor utility or swap MFC"),
                ],
            },
            {
                "sop_id": "SOP-CHUCK-LEAK",
                "title": "ESC Helium Backside Leak Check",
                "abstract": "Pressurize He, monitor decay, inspect ESC seal and focus ring",
                "tools": ["He leak detector"],
                "components": ["Electrostatic Chuck"],
                "reference": "Tool vendor PM manual",
                "steps": [
                    (1, "Place test wafer, pressurize He backside to nominal"),
                    (2, "Close inlet, monitor pressure decay over 60 s"),
                    (3, "If decay above spec, inspect ESC seal and focus ring O-ring"),
                    (4, "Replace seal if damaged, otherwise re-seat focus ring"),
                ],
            },
        ]

        for sop in sops:
            session.run("""
            MERGE (s:SOP {sop_id:$sop_id})
              SET s.title=$title,
                  s.abstract=$abstract,
                  s.tools=$tools,
                  s.reference=$reference
            """, sop_id=sop["sop_id"], title=sop["title"],
                 abstract=sop["abstract"], tools=sop["tools"],
                 reference=sop["reference"])
            for step_no, step_text in sop["steps"]:
                session.run("""
                MATCH (s:SOP {sop_id:$sop_id})
                MERGE (st:SOPStep {sop_id:$sop_id, step_no:$step_no})
                  SET st.text=$step_text
                MERGE (s)-[:HAS_STEP]->(st)
                """, sop_id=sop["sop_id"], step_no=step_no, step_text=step_text)
            for comp in sop["components"]:
                session.run("""
                MATCH (s:SOP {sop_id:$sop_id})
                MATCH (c:Component {name:$comp})
                MERGE (s)-[:TARGETS]->(c)
                """, sop_id=sop["sop_id"], comp=comp)

        # Mechanism -> SOP (Arpitha & Pani stage 4: Recovery)
        session.run("""
        MATCH (m:Mechanism {name:'Residue Accumulation'}),
              (s:SOP {sop_id:'SOP-WET-STRIP'})
        MERGE (m)-[:REMEDIATED_BY {priority:1}]->(s)
        """)
        session.run("""
        MATCH (m:Mechanism {name:'Matcher Detune'}),
              (s1:SOP {sop_id:'SOP-TCP-RECAL'}),
              (s2:SOP {sop_id:'SOP-RF-RECAL'})
        MERGE (m)-[:REMEDIATED_BY {priority:1}]->(s1)
        MERGE (m)-[:REMEDIATED_BY {priority:1}]->(s2)
        """)
        session.run("""
        MATCH (m:Mechanism {name:'MFC Calibration Drift'}),
              (s:SOP {sop_id:'SOP-MFC-CHECK'})
        MERGE (m)-[:REMEDIATED_BY {priority:1}]->(s)
        """)
        session.run("""
        MATCH (m:Mechanism {name:'He Backside Leak'}),
              (s:SOP {sop_id:'SOP-CHUCK-LEAK'})
        MERGE (m)-[:REMEDIATED_BY {priority:1}]->(s)
        """)

    def load_all(self):
        with self.driver.session() as session:
            self.load_equipment_layer(session); print("L1 Equipment loaded.")
            self.load_sensor_layer(session);    print("L2 Sensors loaded.")
            self.load_virtual_sensor_layer(session); print("L3 Virtual sensors loaded.")
            self.load_fault_layer(session);     print("L4 Faults loaded.")
            self.load_cause_layer(session);     print("L5 Causes loaded.")
            self.load_sop_layer(session);       print("L6 SOPs loaded.")
        print("\nKnowledge Graph v2 loaded successfully.")
        print("Estimated nodes: ~120, edges: ~250")


if __name__ == "__main__":
    loader = Neo4jLoaderV2()
    try:
        loader.clear_database()
        loader.create_indexes()
        loader.load_all()
    finally:
        loader.close()
