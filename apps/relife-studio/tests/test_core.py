import tempfile
import unittest
from pathlib import Path

from battery_details import BatteryCatalog, seed_profiles
from bms_engine import ADAPTERS, check_compatibility, evaluate, stress_test
from circuit_studio import CircuitDesign
from models import BatteryProfile

class CoreTests(unittest.TestCase):
    def test_seed_catalog_has_23_source_linked_lfp_records(self):
        rows=seed_profiles()
        self.assertEqual(len(rows),29)
        lfp=[p for p in rows if p.chemistry=='LFP']
        self.assertEqual(len(lfp),23)
        self.assertTrue(all(p.source_url.startswith('https://') and p.soh_pct is None for p in lfp))

    def test_unknowns_are_not_guessed(self):
        p=seed_profiles()[0]
        ok,errors,_=check_compatibility(p,ADAPTERS[0])
        self.assertFalse(ok)
        self.assertTrue(any('Series cell count is unknown' in e for e in errors))

    def test_virtual_profile_and_simulated_fault(self):
        p=BatteryProfile(id='T',name='Test',chemistry='LFP',manufacturer='Demo',model='X',category='EV traction',
            series_cells=8,parallel_cells=1,nominal_voltage_v=25.6,capacity_value=10,capacity_unit='Ah',
            rated_energy_wh=256,charge_limit_a=10,discharge_limit_a=10,mass_kg=2,manufacture_date='2025-01-01',
            condition='Used',cycle_count=20,measured_capacity_ah=8,measured_voltage_v=25.6,
            measured_current_a=2,measured_temperature_c=25,soh_pct=80)
        r=evaluate(p,ADAPTERS[0],'Overcurrent')
        self.assertEqual(r['status'],'FAULT')
        self.assertEqual(r['protection'],'SIMULATED OPEN')

    def test_virtual_stress_returns_soc_soh_and_30_second_trace(self):
        p=BatteryProfile(id='V',name='Virtual',chemistry='LFP',manufacturer='Demo',model='Cell',category='EV traction',
            series_cells=8,parallel_cells=1,nominal_voltage_v=25.6,capacity_value=10,capacity_unit='Ah',
            rated_energy_wh=256,charge_limit_a=10,discharge_limit_a=10,mass_kg=2,manufacture_date='2025-01-01',
            condition='Used',cycle_count=20,measured_capacity_ah=8,measured_voltage_v=25.6,
            measured_current_a=2,measured_temperature_c=25,soh_pct=80,initial_soc_pct=75)
        r=stress_test(p,demand_current_a=2,target_voltage_v=25.6)
        self.assertEqual(len(r['points']),121)
        self.assertIsNotNone(r['points'][-1]['soc_pct'])
        self.assertIsNotNone(r['points'][-1]['soh_pct'])
        self.assertNotEqual(r['points'][-1]['soh_pct'],p.soh_pct)
        self.assertEqual(r['resistance_source'],'profile-specific synthetic virtual plant estimate')

    def test_charge_and_discharge_report_demand_and_distinct_live_soh(self):
        a=BatteryProfile(id='A1',name='A',chemistry='LFP',nominal_voltage_v=12,capacity_value=20,
            capacity_unit='Ah',measured_voltage_v=12,initial_soc_pct=50)
        b=BatteryProfile(id='B2',name='B',chemistry='LFP',nominal_voltage_v=12,capacity_value=20,
            capacity_unit='Ah',measured_voltage_v=12,initial_soc_pct=50)
        discharge=stress_test(a,mode='Discharge',target_voltage_v=12,demand_current_a=2)
        charge=stress_test(a,mode='Charge',target_voltage_v=12,demand_current_a=2)
        other=stress_test(b,mode='Discharge',target_voltage_v=12,demand_current_a=2)
        self.assertLess(discharge['points'][-1]['soc_pct'],discharge['points'][0]['soc_pct'])
        self.assertGreater(charge['points'][-1]['soc_pct'],charge['points'][0]['soc_pct'])
        self.assertLess(discharge['points'][-1]['battery_current_a'],0)
        self.assertGreater(charge['points'][-1]['battery_current_a'],0)
        self.assertEqual(discharge['points'][0]['soh_pct'],None)
        self.assertIsNotNone(discharge['points'][-1]['soh_pct'])
        self.assertNotEqual(discharge['points'][-1]['soh_pct'],other['points'][-1]['soh_pct'])
        self.assertEqual(discharge['demand_current_a'],2)
        self.assertIn('delivered_current_a',discharge)

    def test_seeded_virtual_batteries_do_not_share_one_soh_fallback(self):
        estimates=[]
        for p in seed_profiles():
            result=stress_test(p,demand_current_a=1.0)
            if result['points'][-1]['soh_pct'] is not None:
                estimates.append(round(result['points'][-1]['soh_pct'],1))
        self.assertGreater(len(set(estimates)),1)

    def test_catalog_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            c=BatteryCatalog(Path(d)/'catalog.json'); c.save()
            c2=BatteryCatalog(Path(d)/'catalog.json')
            self.assertEqual(len(c.profiles),len(c2.profiles))

    def test_starter_circuit_contains_named_power_and_signal_nets(self):
        design=CircuitDesign.starter()
        self.assertIn('PACK+',{n.name for n in design.nets})
        self.assertIn('CELL_TAP[n]',{n.name for n in design.nets})
        self.assertIn('U1',{p.ref for p in design.parts})

if __name__=='__main__': unittest.main()
