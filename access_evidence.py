"""Field-level evidence, never an accessibility certification or inferred diagnosis."""

def access_evidence(resource, search, option):
    rows=[]
    for key,label,need in [('step_free','Step-free entrance','Step-free entrance'),('accessible_restroom','Accessible restroom','Accessible restroom')]:
        value=str(resource.get(key,'unknown')).lower().strip()
        rows.append(dict(key=key,label=label,required=need in search['access_needs'],
            status={'yes':'Reported available','no':'Reported unavailable'}.get(value,'Not documented'),
            state={'yes':'reported','no':'unavailable'}.get(value,'unknown'),
            source=resource.get('source','Directory'),date=resource.get('source_checked') or 'Date not supplied'))
    if option.mode=='RTS':
        unknown=option.accessibility_uncertain
        rows.append(dict(key='transit',label='Boarding & vehicle access',required=search['wheelchair_transit'],
            status='Not fully documented' if unknown else 'Reported in transit feed',state='unknown' if unknown else 'reported',
            source='Bundled RTS GTFS',date='See schedule validity'))
    rows.append(dict(key='path',label='Sidewalks & curb cuts',required=False,status='Not verified',state='unknown',source='Street geometry only',date='No field inspection'))
    questions=[]
    for row in rows:
        if row['state']=='unknown' and row['key']=='step_free': questions.append('Is there a step-free route from the sidewalk to the entrance, and is that entrance open during service hours?')
        if row['state']=='unknown' and row['key']=='accessible_restroom': questions.append('Is an accessible restroom available to visitors?')
        if row['state']=='unknown' and row['key']=='transit' and row['required']: questions.append('Can RTS confirm boarding access at the journey stops and an accessible vehicle for this trip?')
    questions.extend(['Am I eligible for this service, and do I need an appointment, referral or documents?', 'What are your current hours, and is the service available on the day I plan to visit?'])
    return dict(fields=rows,questions=questions,headline='A route fits. Physical access still needs checking.',
        required_unknown=sum(r['required'] and r['state']=='unknown' for r in rows),
        demo='demonstration' in resource.get('source','').lower())


def verification_checklist(resource,evidence):
    lines=['FAIRROUTE · ACCESS CHECKLIST',resource['name'],resource.get('address',''),
        'Source: '+resource.get('source',''),'Directory record date: '+(resource.get('source_checked') or 'Not supplied'),
        'Directory record ID: '+str(resource.get('source_id',resource.get('resource_id',''))),'',
        'This is a question sheet, not verified access evidence. No update has been submitted to FCI.','',
        'CALL: '+(resource.get('phone') or 'Number not listed'),'']
    for q in evidence['questions']: lines.extend([q,'Answer: __________________________________________',''])
    lines.extend(['Confirmed by / role: ______________________________','Date and method: _________________________________',
                  'Entrance or path details: _________________________','Follow-up needed: ________________________________',
                  '', 'Provider verification and FCI review are required before any directory update.'])
    return '\n'.join(lines)+'\n'
