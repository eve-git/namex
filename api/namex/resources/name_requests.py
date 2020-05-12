from flask import jsonify, request
from flask_restplus import Namespace, Resource, cors, fields
from namex.utils.util import cors_preflight
from flask import current_app
from namex.models import db, ValidationError
from datetime import timedelta
from pytz import timezone
import os, pysolr, json
from flask_jwt_oidc import AuthError
from namex import jwt

from namex.utils.logging import setup_logging
setup_logging() ## important to do this first


from urllib.parse import unquote_plus
from datetime import datetime

from namex.models import Request, Name, NRNumber, State, User, Comment, Applicant

from namex.services import EventRecorder
from namex.services.virtual_word_condition.virtual_word_condition import VirtualWordConditionService
from namex.services.name_request import convert_to_ascii



from namex.constants import request_type_mapping, RequestAction, EntityTypes


# Register a local namespace for the NR reserve
api = Namespace('nameRequests', description='Public facing Name Requests')

def set_request_type(entity_type, request_action):
    for item in request_type_mapping:
        if(item[1] == entity_type and item[2] == request_action):
            output = item
            break
    request_type =  list(output)
    return request_type[0]


def create_expiry_date(start: datetime, expires_in_days: int, expiry_hour: int = 23, expiry_min: int = 59,
                           tz: timezone = timezone('US/Pacific')) -> datetime:

        date = (start.astimezone(tz) + timedelta(days=expires_in_days)) \
            .replace(hour=expiry_hour, minute=expiry_min, second=0, microsecond=0)

        return date


def update_solr(core,solr_docs):
    SOLR_URL = os.getenv('SOLR_BASE_URL')
    solr = pysolr.Solr(SOLR_URL+'/solr/'+core+'/', timeout=10)
    solr.add(solr_docs,commit=True)

def get_request_sequence():
    seq = db.Sequence('requests_id_seq')
    nr_id = db.engine.execute(seq)
    return nr_id

def get_applicant_sequence():
    seq = db.Sequence('applicants_party_id_seq')
    party_id = db.engine.execute(seq)
    return party_id

def get_name_sequence():
    seq = db.Sequence('names_id_seq')
    name_id = db.engine.execute(seq)
    return name_id

def generate_nr():
    r = db.session.query(NRNumber).first()
    if (r == None):
        # set starting nr number
        last_nr = 'NR L000000'
    else:
        last_nr = r.nrNum
        # TODO:Add a check wheN the number has reached 999999
        # and you need to roll over to the next letter in the alphabet and reseT the number to 000000

    nr_num = NRNumber.get_next_nr_num(last_nr)
    r.nrNum = nr_num
    r.save_to_db()
    #todo add a check that it updated
    return nr_num

def add_language_comment(english_bol, user_id, nr_id):
    lang_comment = Comment()
    lang_comment.examinerId = user_id
    lang_comment.nrId = nr_id
    if english_bol == True:
        # add a coment for the exmainer that say this is nota ENglihs Name
        lang_comment.comment = 'The applicant has indicated the submitted name or names are in English.'
    else:
        lang_comment.comment = 'The applicant has indicated the submitted name or names are not English.'
    return lang_comment

def add_name_comment(user_id, nr_id):
    name_comment = Comment()
    name_comment.examinerId = user_id
    name_comment.nrId = nr_id
    name_comment.comment = 'The submitted name or names is a person name, coined phrase or trademark'
    return name_comment

def set_draft_attributes(name_request, json_data,user_id):
    #TODO: Review additional info stuff from NRO/namex (prev NR for re-applies,no NWPTA?
    name_request.natureBusinessInfo = json_data['natureBusinessInfo']
    if json_data['natureBusinessInfo']:  name_request.natureBusinessInfo = json_data['natureBusinessInfo']

    if json_data['additionalInfo']: name_request.additionalInfo = json_data['additionalInfo']
    if json_data['tradeMark']:  name_request.tradeMark = json_data['tradeMark']
    if json_data['previousRequestId']: name_request.previousRequestId = json_data['previousRequestId']
    name_request.priorityCd = json_data['priorityCd']
    if json_data['priorityCd'] == 'Y':
        name_request.priorityDate = datetime.utcnow().date()

    name_request.submitter_userid = user_id
    # XPRO
    if json_data['xproJurisdiction']: name_request.xproJurisdiction = json_data['xproJurisdiction']
    # for MRAS participants
    if json_data['homeJurisNum']: name_request.homeJurisNum = json_data['homeJurisNum']
    # for existing businesses
    if json_data['corpNum']: name_request.corpNum = json_data['corpNum']

    return name_request

def set_applicant_attributes(json_data,nr_id):
    # applicant, contact and address info
    for applicant in json_data.get('applicants', None):
        nrd_app = Applicant()
        party_id = get_applicant_sequence()
        nrd_app.nrId = nr_id
        nrd_app.partyId = party_id
        nrd_app.lastName = convert_to_ascii(applicant['lastName'])
        nrd_app.firstName = convert_to_ascii(applicant['firstName'])
        if applicant['middleName']: nrd_app.middleName = convert_to_ascii(applicant['middleName'])
        nrd_app.contact = convert_to_ascii(applicant['contact'])
        if applicant['middleName']: nrd_app.middleName = convert_to_ascii(applicant['middleName'])
        if applicant['clientFirstName']: nrd_app.clientFirstName = convert_to_ascii(applicant['clientFirstName'])
        if applicant['clientLastName']:  nrd_app.clientLastName = convert_to_ascii(applicant['clientLastName'])
        if applicant['phoneNumber']: nrd_app.phoneNumber = convert_to_ascii(applicant['phoneNumber'])
        if applicant['faxNumber']: nrd_app.faxNumber = convert_to_ascii(applicant['faxNumber'])
        nrd_app.emailAddress = convert_to_ascii(applicant['emailAddress'])
        nrd_app.addrLine1 = convert_to_ascii(applicant['addrLine1'])
        if applicant['addrLine2']: nrd_app.addrLine2 = convert_to_ascii(applicant['addrLine2'])
        nrd_app.city = convert_to_ascii(applicant['city'])
        nrd_app.stateProvinceCd = applicant['stateProvinceCd']
        nrd_app.postalCd = convert_to_ascii(applicant['postalCd'])
        nrd_app.countryTypeCd = applicant['countryTypeCd']

    return nrd_app


@cors_preflight("POST")
@api.route('/', strict_slashes=False, methods=['POST', 'OPTIONS'])
class NameRequest(Resource):
    applicant_model = api.model('applicant_model',{
                                    'lastName': fields.String(attribute='lastName'),
                                    'firstName': fields.String(attribute='firstName'),
                                    'middleName': fields.String('Applicant middle name or initial'),
                                    'contact': fields.String('Applicant contact person last and first name'),
                                    'clientFirstName': fields.String('Client first name'),
                                    'clientLastName': fields.String('Client last name'),
                                    'phoneNumber': fields.String('contact phone number'),
                                    'faxNumber': fields.String('contact fax number'),
                                    'emailAddress': fields.String('contact email'),
                                    'addrLine1': fields.String('First address line'),
                                    'addrLine2': fields.String('Second address line'),
                                    'city': fields.String('City'),
                                    'stateProvinceCd': fields.String('Province or state code'),
                                    'postalCd': fields.String('postal code or zip code'),
                                    'countryTypeCd': fields.String('country code')
                                })
    consent_model = api.model('consent_model',{
                        'consent_word': fields.String('A word that requires consent')
    })
    name_model = api.model('name_model',{
                                    'choice': fields.Integer('Name choice'),
                                    'name': fields.String('Name'),
                                    'name_type_cd': fields.String('For company or assume dname', enum=['CO', 'AS']),
                                    'state': fields.String('The state of the Name'),
                                    'designation': fields.String('Name designation based on entity type'),
                                    'conflict1_num': fields.String('the corp_num of teh matching name'),
                                    'conflict1': fields.String('The mathcing corp name'),
                                    'consent_words': fields.Nested(consent_model)
                             })

    nr_request = api.model('name_request', {'entity_type': fields.String('The entity type'),
                                      'request_action': fields.String('The action requested by the user'),
                                      'stateCd': fields.String('The state of the NR'),
                                      'english': fields.Boolean('Set when the name is English only'),
                                      'nameFlag': fields.Boolean('Set when the name is a person'),
                                      'additionalInfo': fields.String('Additional NR Info'),
                                      'natureBusinessInfo': fields.String('The nature of business'),
                                      'trademark': fields.String('Registered Trademark'),
                                      'previousRequestId': fields.Integer('Internal Id for ReApplys'),
                                      'priorityCd': fields.String('Set to Yes if it is  priority going to examination'),
                                      'submit_count': fields.Integer(
                                          'Used to enforce the 3 times only rule for Re-Applys'),
                                      'xproJurisdiction': fields.String(
                                          'The province or country code for XPRO requests'),
                                      'homeJurisNum': fields.String(
                                          'For MRAS participants, their home jursidtcion corp_num'),
                                      'corpNum': fields.String(
                                          'For companies already registered in BC, their BC corp_num'),
                                      'applicants': fields.Nested(applicant_model),
                                      'names': fields.Nested(name_model)
                                 })

    @api.expect(nr_request)
    @cors.crossdomain(origin='*')
    #@jwt.requires_auth
    def post(self, *args, **kwargs):
        json_data = request.get_json()
        if not json_data:
            return jsonify({'message': 'No input data provided'}), 400

        restricted = VirtualWordConditionService()

        user = User.find_by_username('name_request_service_account')
        user_id = user.id

        name_request = Request()

        nr_num = generate_nr()
        nr_id = get_request_sequence()

        #set the request attributes
        name_request.id = nr_id
        name_request.submittedDate=datetime.utcnow()
        name_request.requestTypeCd = set_request_type(json_data['entity_type'], json_data['request_action'])
        name_request.nrNum=nr_num

        if(json_data['stateCd'] == 'COND-RESERVE'):
            name_request.consentFlag =  'Y'

        if json_data['stateCd'] in [State.RESERVED, State.COND_RESERVE]:
            name_request.expirationDate= create_expiry_date(start=name_request.submittedDate, expires_in_days=56, tz=timezone('UTC'))

        name_request.stateCd=json_data['stateCd']
        name_request.entity_type_cd = json_data['entity_type']
        name_request.request_action_cd= json_data['request_action']
        #set this to name_request_service_account
        name_request.userId = user_id

        lang_comment = add_language_comment(json_data['english'],user_id, nr_id)
        name_request.comments.append(lang_comment)

        if  json_data['nameFlag'] == True:
            name_comment = add_name_comment(user_id, nr_id)
            name_request.comments.append(name_comment)

        if json_data['submit_count'] is None:
            name_request.submitCount = 1
        else:
            name_request.submitCount = + 1

        if json_data['stateCd'] in [State.RESERVED, State.COND_RESERVE]:
            name_request.save_to_db()
            nrd = Request.find_by_nr(name_request.nrNum)
        elif json_data['stateCd'] == 'DRAFT':
            #set request header attributes
            name_request = set_draft_attributes(name_request, json_data,user_id)
            name_request.save_to_db()
            nrd = Request.find_by_nr(name_request.nrNum)
            #set applicant attributes
            nrd_app=set_applicant_attributes(json_data,nr_id)
            nrd.applicants.append(nrd_app)

        for name in json_data.get('names', None):
            submitted_name = Name()
            name_id = get_name_sequence()
            submitted_name.id = name_id

            submitted_name.choice = name['choice']
            submitted_name.name = name['name']

            if (name['name_type_cd']):
                submitted_name.name_type_cd = name['name_type_cd']
            else:
                submitted_name.name_type_cd = 'CO'

            if (json_data['stateCd'] == State.DRAFT):
                submitted_name.state = 'NE'
            else:
                submitted_name.state = json_data['stateCd']

            if name['designation']: submitted_name.designation = name['designation']
            submitted_name.nrId = nr_id

            if json_data['stateCd'] in [State.RESERVED, State.COND_RESERVE]:
                decision_text = None
                # only capturing one conflict
                if (name['conflict1_num']):
                    submitted_name.conflict1_num = name['conflict1_num']
                    if name['conflict1']: submitted_name.conflict1 = name['conflict1']
                    # conflict text same as Namex
                    decision_text = 'Consent is required from ' + name['conflict1'] + '\n' + '\n'
                else:
                    submitted_name.conflict1_num = None
                    submitted_name.conflict1 = None

                for consent in name['consent_words']:
                    cnd_instructions = None
                    cnd_instructions = restricted.get_word_condition_instructions(consent)

                    if (decision_text is None):
                        decision_text = cnd_instructions + '\n'
                    else:
                        decision_text += consent + '- ' + cnd_instructions + '\n'

                submitted_name.decision_text = decision_text
            nrd.names.append(submitted_name)
        #save names
        nrd.save_to_db()

        #TODO: Need to add verification that the save was successful.
       #update solr for reservation
        if(json_data['stateCd'] in ['RESERVED', 'COND-RESERVE']):
            solr_name = nrd.names[0].name
            solr_docs=[]
            nr_doc = {"id": name_request.nrNum, "name": solr_name , "source": "NR",
                      "start_date": name_request.submittedDate.strftime("%Y-%m-%dT%H:%M:00Z")}

            solr_docs.append(nr_doc)
            update_solr('possible.conflicts',solr_docs)

        current_app.logger.debug(name_request.json())
        return jsonify(name_request.json()), 200





