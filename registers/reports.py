import xlsxwriter


def itsr_staff_discrepancies(fileobj, it_systems):
    """This function will return an Excel workbook of IT Systems where owner & custodian details have issues.
    Pass in a file-like object to write into, plus a queryset of IT Systems.
    """
    discrepancies = {}

    for sys in it_systems:
        if sys.owner and not sys.owner.active:
            if sys.system_id not in discrepancies:
                discrepancies[sys.system_id] = []
            discrepancies[sys.system_id].append((sys.name, 'Owner {} is inactive'.format(sys.owner)))
        if sys.owner and sys.owner.cost_centre != sys.cost_centre:
            if sys.system_id not in discrepancies:
                discrepancies[sys.system_id] = []
            discrepancies[sys.system_id].append((sys.name, 'Owner {} cost centre ({}) differs from {} cost centre ({})'.format(sys.owner, sys.owner.cost_centre, sys.name, sys.cost_centre)))
        if sys.technology_custodian and not sys.technology_custodian.active:
            if sys.system_id not in discrepancies:
                discrepancies[sys.system_id] = []
            discrepancies[sys.system_id].append((sys.name, 'Technology custodian {} is inactive'.format(sys.technology_custodian)))
        if sys.information_custodian and not sys.information_custodian.active:
            if sys.system_id not in discrepancies:
                discrepancies[sys.system_id] = []
            discrepancies[sys.system_id].append((sys.name, 'Information custodian {} is inactive'.format(sys.information_custodian)))
        if sys.cost_centre and not sys.cost_centre.active:
            if sys.system_id not in discrepancies:
                discrepancies[sys.system_id] = []
            discrepancies[sys.system_id].append((sys.name, 'Cost centre {} is inactive'.format(sys.cost_centre)))


    with xlsxwriter.Workbook(
        fileobj,
        {
            'in_memory': True,
            'default_date_format': 'dd-mmm-yyyy HH:MM',
            'remove_timezone': True,
        },
    ) as workbook:
        sheet = workbook.add_worksheet('Discrepancies')
        sheet.write_row('A1', ('System ID', 'System name', 'Discrepancy'))
        row = 1
        for k, v in discrepancies.items():
            for issue in v:
                sheet.write_row(row, 0, [k, issue[0], issue[1]])
                row += 1
        sheet.set_column('A:A', 10)
        sheet.set_column('B:B', 40)
        sheet.set_column('C:C', 100)

    return fileobj