# -*- coding: utf-8 -*-
"""
The MIT License (MIT)
Copyright © 2019 by Michael McGurrin

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the “Software”), to deal in the Software without restriction, 
including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, 
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, 
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial 
portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, 
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND 
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR 
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION 
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
from pytz import timezone
import logging

from ask_sdk_core.dispatch_components import (AbstractRequestHandler, AbstractExceptionHandler, 
    AbstractRequestInterceptor)
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_model.ui import SimpleCard
from ask_sdk.standard import StandardSkillBuilder
import ask_sdk_dynamodb
skill_persistence_table = 'toll_routes'

# Skill Builder object
sb = StandardSkillBuilder(
    table_name=skill_persistence_table, auto_create_table=False, 
    partition_keygen=ask_sdk_dynamodb.partition_keygen.user_id_partition_keygen)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

toll_hours = """Eastbound tolls are charged between 5:30 and 9:30 am,
        Monday through Friday. westbound tolls are charged between 3 and 7 pm,
        Monday through Friday. There are no toll or HOV requirements on Federal
        holidays or at all other times."""
information = toll_hours + """ <break time="1.5s"/>All users require an E-Z Pass for paying tolls. If
you carpool with 2 or more people, you can use the lanes inside the beltway for free.
You'll need an E-Z Pass Flex set to HOV modes to avoide the toll. Toll rates are
set dynamicall, based on the volume of traffic on the toll roads. The values
provided in this app are the current tolls, and they may change before you 
reach I-66."""

# Dictionary of toll zone names and numbers
zone_names = {'3100':'Capital Beltway Beginning', '3110': 'Lee Highway', '3120': "Fairfax Drive",
         '3130': 'Spout Run Parkway', '3200':'Glebe Road', 3210: 'Sycamore Street',
         '3220': 'Leesburg pike', '3230':'Capital Beltway end'}

# Dictionary mapping interchanges to tolling points
#Eastbound / Inbound
in_entrances = {'i sixty six': '3100', 'i four ninety five': '3100', 'route one twenty three': '3110',
                'route seven': '3110', 'route two sixty seven': '3110', 'sycamore streete': '3120',
                'glebe road':'3130'}
in_exits = {'route seven':'3100', 'washington boulevard': '3110', 'westmoreland street': '3110',
            'fairfax drive': '3120', 'lee highway': '3130', 'rosslyn': '3130', 'pentagon':' 3130',
            'washington': '3130'}
# There are two Lee Highway entrances, at Scott Street and Spout Run, but same toll zone, so combined
out_entrances = {'washington': '3200', 'pentagon': '3200', 'lee highway': '3200',
                 'fairfax drive': '3210', 'washington boulevard': '3220', 'route seven': '3230'}
out_exits = {'glebe road': '3200', 'sycamore street': '3210', 'route two sixty seven': '3220',
                 'route seven': '3220', 'i four ninety five': '3230', 'i sixty six': '3230'}

def convert_to_currency(toll):
    toll = toll.split('.')
    string = toll[0] + ' dollars and ' + toll[1][0:2] + ' cents.' 
    return string

def get_travel_times():
    """
    Get Travel Times for I-66 and US-50 from Beltway to and from TR Bridge
    """
    travel_url = 'http://www.511virginia.org/mobile/?menu_id=traveltimes'
    travel = requests.get(travel_url)
    soup = BeautifulSoup(travel.text, 'html.parser')
    table = soup.find(class_ = 'data_table')
    for row in table.findAll('tr'):
        cells = row.findAll('td')
        # Find Relevant I-66 rows
        if len(cells) == 7:
            if cells[4].text == 'from The Capital Beltway to The Theodore Roosevelt Memorial Bridge':
                I66_inbound_speed = cells[5].text
                I66_inbound_time = cells[6].text
            if cells[4].text == 'from The Theodore Roosevelt Memorial Bridge to The Capital Beltway':
                I66_outbound_speed = cells[5].text
                I66_outbound_time = cells[6].text
            # Find Relevant US_50 rows
            if cells[4].text == 'from Capital Beltway to District of Columbia at the Theodore Roosevelt Memorial Bridge':
                US50_inbound_speed = cells[5].text
                US50_inbound_time = cells[6].text
            if cells[4].text == 'from District of Columbia at the Theodore Roosevelt Memorial Bridge to Capital Beltway':
                US50_outbound_speed = cells[5].text
                US50_outbound_time = cells[6].text
    return (I66_inbound_speed, I66_inbound_time, I66_outbound_speed, 
           I66_outbound_time, US50_inbound_speed, US50_inbound_time, 
           US50_outbound_speed, US50_outbound_time)

def get_tolls():    
    """
    Get tolls for I-66 from Beltway to and from TR Bridge
    Note that the furthest inbound tolling spot is Spout Run
    """
    tolls_url = 'https://smarterroads.org/dataset/download/29'
    file = 'TollingTripPricing-I66/TollingTripPricing_current.xml'
    token = '7MEheYSiJ8Kzi96cWcoWpIE8keZBpDiukaPKbd3idD02SP4VjJwZcLrwtieTDd3P'
    request_string = tolls_url + '?file=' + file + '&token=' + token
    tolls = requests.get(request_string)
    soup = BeautifulSoup(tolls.text, 'xml')
    if soup is None:
        time.sleep(2)
        soup = BeautifulSoup(tolls.text, 'xml')  
    if soup is None:
        logger.info('No toll data is available')
        tolls = {'none':'none'}
    else:
        entries = soup.find_all('opt')[::-1]  # Need to reverse, since want 2nd (later time) entries
        tolls = {}
        for entry in entries:
            tolls[entry['StartZoneID'] +' '+ entry['EndZoneID']] = convert_to_currency(entry['ZoneTollRate'])
    logger.info('tolls')
    return(tolls)        

class SkillInitializer(AbstractRequestInterceptor):
    """If starting, get the toll and speed data and store in session attributes"""
    def process(self, handler_input):
#         if handler_input.request_envelope.session.new == True:
          if not handler_input.attributes_manager.session_attributes:
             I66_inspeed, I66_intime, I66_outspeed, I66_outtime, US50_inspeed, US50_intime, \
             US50_outspeed, US50_outtime = get_travel_times()
             all_tolls = get_tolls()
             logger.debug(all_tolls)
             attr = {'I66_inspeed': I66_inspeed, 'I66_intime': I66_intime, 'I66_outspeed': I66_outspeed,
                     'I66_outtime': I66_outtime, 'US50_inspeed': US50_inspeed, 'US50_intime': US50_intime,
                     'US50_outspeed': US50_outspeed, 'US50_outtime': US50_outtime, 
                     'all_tolls': all_tolls}
             handler_input.attributes_manager.session_attributes = attr  
             
class LaunchRequestHandler(AbstractRequestHandler):
     def can_handle(self, handler_input):
         # type: (HandlerInput) -> bool
         return is_request_type("LaunchRequest")(handler_input)

     def handle(self, handler_input):
         # type: (HandlerInput) -> Response   
        logger.debug("about to get per_attr")
        per_attr = handler_input.attributes_manager.persistent_attributes
        logger.debug('got past setting per_attr')
        logger.debug(per_attr)
        session_attr = handler_input.attributes_manager.session_attributes
        costs = session_attr.get('all_tolls') 
        end_session_flag = False # Set to true if toll data isn't available from VDOT
        logger.debug(f"""costs are: {costs}""")
        if 'none' in costs:
            logger.debug('failed finding data')
            speech_text = """I'm sorry, but tolling information is temporarily unavailable.
                Please try again in a minute."""
            end_session_flag = True
            
        else:   
            if per_attr == {}:   #User doesn't have any favorite OD pairs
                logger.debug('per_attr not found')
                speech_text = """Welcome. To get the current tolls, you need to provide the direction, entrance.
                and exit. Say what is the current inbound or outbound toll between a and b, where a in your 
                entrance and b is your exit. You can also say what are the inbound speeds or what are the outbound
                speeds. For a complete explanation of features, say help."""        
            else:
                # Probably should write better, more focussed checks to see if the user
                # has frequent routes saved, but for now, just using try... except
                logger.debug('got to has record part of launch')
                local_hour = datetime.now(timezone('US/Eastern')).hour
                logger.debug(f"""Local hour is {local_hour}""")
                if local_hour < 12 and 'in_entrance' in per_attr:
                    direction = 'inbound'
                    entrance_name = per_attr["in_entrance"] 
                    exit_name = per_attr["in_exit"]  
                    start_zone = in_entrances[entrance_name]
                    end_zone = in_exits[exit_name]
                    toll_od = start_zone + ' ' + end_zone
                    cost = costs[toll_od]    
                    speech_text = f"""The current {direction} toll from {entrance_name} to {exit_name}
                    is {cost}.""" 
                elif local_hour >= 12 and 'out_entrance' in per_attr:
                    direction = 'outbound'
                    entrance_name = per_attr["out_entrance"] 
                    exit_name = per_attr["out_exit"]  
                    start_zone = out_entrances[entrance_name]
                    end_zone = out_exits[exit_name]
                    toll_od = start_zone + ' ' + end_zone
                    cost = costs[toll_od]
                    speech_text = f"""The current {direction} toll from {entrance_name} to {exit_name} 
                    is {cost}."""  
                else:  
                    speech_text = """Welcome. You can find the current tolls on I-66 inside the Beltway,
                    and also check on speeds. You can also save your most frequent inbound and outbound routes.
                    Say "help" to get information on the available commands"""            
        handler_input.response_builder.speak(speech_text).set_card(
            SimpleCard("I-66 Tolls", speech_text)).set_should_end_session(end_session_flag)     
        return handler_input.response_builder.response            
  
class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = """This skill provides information on the current tolls being charged on I-66 
        inside the Beltway, between the Capital Beltway and the Teddy Roosevelt Bridge, as well as the
        travel speeds on I-66 and Route 50. <break time="1.0s"/>
        To get the toll, say "Alexa, what is the inbound or outbound toll from a to b, where a is the
        entrance and b is the exit. To get a list of entrances or exits, say "Alexa, what are the inbound
        or outbound entrances or exits." <break time="1.0s"/>
        To get the speeds, just say Alexa, what are the inbound or outbound speeds.
        Would you like to hear more?"""  
#        return handler_input.response_builder.speak(speech_text).response 
        reprompt = "What would you like to know?"
        handler_input.response_builder.speak(speech_text).ask(reprompt).set_should_end_session(False) 
#        return handler_input.response_builder.speak(speech_text).response 
        return handler_input.response_builder.response
    
class CancelAndStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input)
                 or is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "Goodbye!"

        handler_input.response_builder.speak(speech_text).set_card(
            SimpleCard("I-66 Tolls", speech_text))
        return handler_input.response_builder.response
    
class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        # any cleanup logic goes here

        return handler_input.response_builder.response
    
class AllExceptionHandler(AbstractExceptionHandler):

    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        # Log the exception in CloudWatch Logs
        logger.info(exception)

        speech = """Sorry, something went wrong. Please try it again or 
        ask for help. Remember to specify the direction, inbound or outbound, 
        when asking for the toll between two points."""
        handler_input.response_builder.speak(speech).ask(speech)
        return handler_input.response_builder.response   
       
class GetTollHoursHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("get_toll_hours")(handler_input)

    def handle(self, handler_input):
        speech_text = toll_hours
        return handler_input.response_builder.speak(speech_text).response
    
class GetDetailsHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("get_details")(handler_input)

    def handle(self, handler_input):
        speech_text = information
        return handler_input.response_builder.speak(speech_text).response
    
class GetSpeeds(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("get_speeds")(handler_input)

    def handle(self, handler_input):
        logger.debug('got to GetSpeeds')
        slots = handler_input.request_envelope.request.intent.slots
        direction = slots["direction"].resolutions.resolutions_per_authority[0].values[0].value.name
        session_attr = handler_input.attributes_manager.session_attributes
        if direction == "inbound":
           us50speed = session_attr.get('US50_inspeed') 
           i66speed = session_attr.get('I66_inspeed')
           us50time = session_attr.get('US50_intime') 
           i66time = session_attr.get('I66_intime')
           us50speed = us50speed[:-4]   # drop the 'mph'
           i66speed = i66speed[:-4]   # drop the 'mph' 
           speech_text = f"""The {direction} speed on US50 is currently 
           {us50speed} miles per hour and the travel time is {us50time}. 
           The {direction} speed on I66 is currently {i66speed} miles per hour
           and the travel time is {i66time}."""
        elif direction == "outbound":
           us50speed = session_attr.get('US50_outspeed') 
           i66speed = session_attr.get('I66_outspeed')
           us50time = session_attr.get('US50_outtime') 
           i66time = session_attr.get('I66_outtime') 
           us50speed = us50speed[:-4]   # drop the 'mph'
           i66speed = i66speed[:-4]   # drop the 'mph'  \
           speech_text = f"""The {direction} speed on US50 is currently 
           {us50speed} miles per hour and the travel time is {us50time}. 
           The {direction} speed on I66 is currently {i66speed} miles per hour
           and the travel time is {i66time}."""                    
        return handler_input.response_builder.speak(speech_text).response
    
class ListInterchanges(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("list_interchanges")(handler_input)

    def handle(self, handler_input):
        slots = handler_input.request_envelope.request.intent.slots
        interchange_type = slots["interchange_type"].resolutions.resolutions_per_authority[0].values[0].value.name
        direction = slots["direction"].resolutions.resolutions_per_authority[0].values[0].value.name
        if direction == "inbound":
            if interchange_type == 'entrances':
                speech_text = f"""The {direction} {interchange_type} are: {list(in_entrances.keys())}"""
            else:
                speech_text = f"""The {direction} {interchange_type} are: {list(in_exits.keys())}"""            
        else:
            if interchange_type == 'entrances':    
                speech_text = f"""The {direction} {interchange_type} are: {list(out_entrances.keys())}"""                
            else:
                speech_text = f"""The {direction} {interchange_type} are: {list(out_exits.keys())}"""                     
        return handler_input.response_builder.speak(speech_text).response    
    
class GetToll(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name('get_toll')(handler_input)
    
    def handle(self, handler_input):
        logger.debug('got to GetToll')
        slots = handler_input.request_envelope.request.intent.slots
        direction = slots["direction"].resolutions.resolutions_per_authority[0].values[0].value.name
        entrance_name = slots["entrance"].resolutions.resolutions_per_authority[0].values[0].value.name
        exit_name = slots["exit"].resolutions.resolutions_per_authority[0].values[0].value.name
        session_attr = handler_input.attributes_manager.session_attributes
        costs = session_attr.get('all_tolls') 
        logger.debug(costs)
        logger.debug(f"""requested entrance and exits were: {entrance_name} and {exit_name}""")
        if direction == 'inbound':
            start_zone = in_entrances[entrance_name]
            end_zone = in_exits[exit_name]
        else: 
            start_zone = out_entrances[entrance_name]
            end_zone = out_exits[exit_name]
        toll_od = start_zone + ' ' + end_zone
        logger.info(toll_od)
        cost = costs[toll_od]   
        speech_text = f"""The current toll from {entrance_name} to {exit_name} is {cost}."""
        return handler_input.response_builder.speak(speech_text).response
    
class SaveTrip(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name('save_trip')(handler_input)
    
    def handle(self, handler_input):
        logger.debug('got to SaveTrip')
        slots = handler_input.request_envelope.request.intent.slots
        direction = slots["direction"].resolutions.resolutions_per_authority[0].values[0].value.name
        entrance_name = slots["entrance"].resolutions.resolutions_per_authority[0].values[0].value.name
        exit_name = slots["exit"].resolutions.resolutions_per_authority[0].values[0].value.name
        fav = handler_input.attributes_manager.persistent_attributes
        if direction == 'inbound':
            fav['in_entrance'] = entrance_name
            fav['in_exit'] = exit_name
        else: 
            fav['out_entrance'] = entrance_name
            fav['out_exit'] = exit_name
        handler_input.attributes_manager.persistent_attributes = fav 
        handler_input.attributes_manager.save_persistent_attributes()          
        speech_text = f"""Your most frequent {direction} trip has been saved."""           
        return handler_input.response_builder.speak(speech_text).response
    
class GetFavs(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name('get_favs')(handler_input)
    
    def handle(self, handler_input):
        logger.debug('got to GetFavs')
        per_attr = handler_input.attributes_manager.persistent_attributes
        try:
            if not per_attr:   #User doesn't have any favorite OD pairs
                speech_text = "You don't have any saved routes"
            else:
                if 'in_entrance' in per_attr and 'in_exit' in per_attr:
                    entrance_name = per_attr["in_entrance"] 
                    exit_name = per_attr["in_exit"]  
                    speech_text = f"""Your saved inbound route is from 
                       {entrance_name} to {exit_name}. """
                else:
                    speech_text = "You don't have a saved inbound route. "
                if 'out_entrance' in per_attr and 'out_exit' in per_attr:
                    entrance_name = per_attr["out_entrance"] 
                    exit_name = per_attr["out_exit"]  
                    speech_text = speech_text+ f"""Your saved outound route is from 
                       {entrance_name} to {exit_name}. """
                else:
                    speech_text = speech_text + "You don't have a saved outbound route. "            
        except Exception as e:
            logger.info(e)
         
        return handler_input.response_builder.speak(speech_text).response
     
class GetSpecificHelp(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name('get_specific_help')(handler_input)
    
    def handle(self, handler_input):
        logger.debug('got to GetSpecificHelp')
        slots = handler_input.request_envelope.request.intent.slots
        help_type = slots["help_type"].resolutions.resolutions_per_authority[0].values[0].value.name
        if help_type == "tolls":
            speech_text = """To get the toll, say "Alexa, what is the inbound or outbound toll from a to b, 
               where a is the entrance and b is the exit. To get a list of entrances or exits, 
               say "Alexa, what are the inbound or outbound entrances or exits."""
        elif help_type == "speeds":
            speech_text = """To get the speeds, just say "Alexa, what are the inbound or outbound speeds."""         
        else:
            speech_text = """To save your most frequent inbound and outbound route, say "save my trip" and 
               Alexa will guide you through the process. Once you've done that, just opening the skill 
               will provide the current toll on your inbound route if it's morning, or your outbound route
               if it's afternoon or evening."""             
        return handler_input.response_builder.speak(speech_text).response    

class YesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.YesIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = """OK. To save your most frequent inbound and outbound route, say "save my trip" 
        and Alexa will guide you through the process. Once you've done that, just opening the skill 
        will provide the current toll on your inbound route if it's morning, or your outbound route 
        if it's afternoon or evening. <break time="1.0s"/>
        Finally, you can ask for the toll hours or for additional information on the tolls."""          
        handler_input.response_builder.speak(speech_text).set_should_end_session(False) 
#        return handler_input.response_builder.speak(speech_text).response 
        return handler_input.response_builder.response  
    
    
class NoIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.NoIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "O.K."
        handler_input.response_builder.speak(speech_text).set_should_end_session(False) 
#        return handler_input.response_builder.speak(speech_text).response 
        return handler_input.response_builder.response  
    
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(GetSpeeds())
sb.add_request_handler(GetToll())
sb.add_request_handler(GetTollHoursHandler())
sb.add_request_handler(GetDetailsHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelAndStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(AllExceptionHandler())
sb.add_global_request_interceptor(SkillInitializer())
sb.add_request_handler(SaveTrip())
sb.add_request_handler(GetFavs())
sb.add_request_handler(ListInterchanges())
sb.add_request_handler(GetSpecificHelp())
sb.add_request_handler(YesIntentHandler())
sb.add_request_handler(NoIntentHandler())
handler = sb.lambda_handler()



            
