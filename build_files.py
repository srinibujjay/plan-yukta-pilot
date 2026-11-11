"""Regenerate the downloadable template and sample workbook: python build_files.py"""
from plan_yukta.template import build_workbook
from sample.make_sample import build

if __name__ == '__main__':
    build_workbook(None, 'static/PlanYukta_Template.xlsx')
    data = build()
    build_workbook(data, 'static/PlanYukta_Sample.xlsx', formula_rows=len(data['osat_wip']) + 200)
    print('built static/PlanYukta_Template.xlsx and static/PlanYukta_Sample.xlsx')
