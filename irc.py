import sys, socket, ssl, time, os
from multiprocessing import Process, Event, Queue

from com_manager import Commanager
from parser import Parser
from database_manager import DBM
from utils import RETRY_DELAY, RETRY_TIMES, MULTI, COMMANDS_DIR, SCHEMA

import ircerror

class IRC:
    """ Class that do most of the irc work """

    def __init__(self, host, port, nick, channels, database, prefix, password, ssl):
        self.host = IRC.check_host(host)
        self.port = IRC.check_port(port)
        self.nick = IRC.check_nick(nick)
        self.channels = IRC.check_channels(channels)
        self.prefix = IRC.check_prefix(prefix)
        self.password = IRC.check_password(password)
        self.ssl = IRC.check_ssl(ssl)

        # load commands
        print("Loading commands...")
        self.command_manager = Commanager(COMMANDS_DIR)
        print(self.command_manager.commands)
        print("...done!")

        # create database
        try:
            print(database)
            self.database = DBM(database, SCHEMA)
        except:
            raise


    def connect(self):
        """ Main connection structure. Socket generation and check on connection status """

        for retry_n in range(RETRY_TIMES):
            try:
                ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                ircsock.connect((self.host, self.port))

                if self.ssl:
                    # secure connection
                    ircsock = ssl.wrap_socket(ircsock)

                self.server_login(ircsock)

                if MULTI:
                    # multiprocess ramenbot
                    self.start_multi(ircsock)
                else:
                    # single process ramenbot
                    self.start_single(ircsock)

            except ConnectionRefusedError as e:
                print(e, file=sys.stderr)
                pass

            except:
                raise

            print("Retrying in {}s...".format(RETRY_DELAY * (retry_n + 1), file=sys.stderr))
            time.sleep(RETRY_DELAY * (retry_n + 1))


    def server_login(self, ircsock):
        """ Connects to the irc server and if you set up a password it logs to NickServ """

        ircsock.send(bytes("NICK {}\r\n".format(self.nick), "UTF-8"))
        time.sleep(.5)
        ircsock.send(bytes("USER {} {} {} :ramenbot\r\n".format(self.nick, self.nick, self.nick), "UTF-8"))
        time.sleep(.5)

        if self.password:
            print("pass")
            

    def chan_join(self, ircsock):
        print("Joining Chans...")
        for chan in self.channels: ircsock.send(bytes("JOIN {}\r\n".format(chan), "UTF-8"))


    def ping(ircsock, arg):
        print("Pong!")
        ircsock.send(bytes("PONG :{}\r\n".format(arg), "UTF-8")) 


    def kicked(ircsock, arg):
        print("Kicked!")


    ################################### multi process ##########################################
    ############################################################################################

    def start_multi(self, ircsock):
        """ Start main bot function [obtain msg, store command] / [execute command, send output back] that supports multiprocess """      
        
        msg_queue = Queue()
        queue_event = Event()

        producer = Process(target=self.listening, args=(ircsock, queue_event, msg_queue,))
        consumer = Process(target=self.answering, args=(ircsock, queue_event, msg_queue,))

        producer.start()
        consumer.start()
        producer.join()
        consumer.join()


    def listening(self, ircsock, queue_event, queue):
        """ Obtain msg, queue command """

        try:
            # get msg
            for msg in self.get_msg(ircsock):
                if not msg: raise ircerror.IRCShutdown("Server closed connection")

                # parsing irc msg
                sender, receiver, irc_command, irc_args = Parser.parse_msg(msg)

                # if irc commands are not PRIVMSG handle them right away
                # and get next msg
                if irc_command != 'PRIVMSG':
                    if irc_command == 'PING':
                        IRC.ping(ircsock, irc_args)
                    elif irc_command == 'KICK':
                        IRC.kicked(ircsock, irc_args)
                    elif irc_command == 'MODE':
                        self.chan_join(ircsock)

                    continue

                # triggering commands 
                queue.put(self.command_manager.mkcom("checkon", sender, sender, receiver))  

                ####################
                # command handling #
                ####################

                # find and create command
                name, args = Parser.find_command(irc_args, self.prefix)
                command = self.command_manager.mkcom(name, args, sender, receiver) 
                
                # if not command get next msg
                if not command: continue

                # check if queue is full
                if queue.full(): queue_event.wait() 
                queue.put(command)
                # unlock answering process
                queue_event.set()
        
        except ircerror.IRCShutdown as e:
            print(e.description, file=sys.stderr)

        finally:
            print("Closing listening process")
            if queue.full(): queue_event.wait()
            queue.put(None)
            queue_event.set()


    def answering(self, ircsock, queue_event, queue):
        """ Get command, execute it, and send back the output """

        try:
            while True:
                # if queue empty wait for producer to add commands
                if queue.empty(): queue_event.wait()

                # get command from queue
                command = queue.get()

                # if command is none, then listening process closed
                # and we need to close this process as well
                if command == None: break;

                # execute command
                self.send(ircsock, command)

                # unlock listening process if locked (can happen if queue is full)
                queue_event.set()

        finally:
            print("Closing answering process")
        

    ############################################################################################
    ############################################################################################


    ################################### single process #########################################
    ############################################################################################

    def start_single(self, ircsock):
        return True

    
    def get_msg(self, ircsock):
        line_buffer = str()

        while True:
            readbuffer = ircsock.recv(1024).decode("UTF-8")
            # if buffer is '', then connection was close
            if not readbuffer: yield readbuffer

            # this fixes msg if it gets truncated
            try:
                head, *mid, tail = readbuffer.split('\n') 

                yield line_buffer + head

                line_buffer = str()

                for msg in mid:
                    yield msg

                line_buffer = line_buffer + tail

            except ValueError:
                line_buffer = line_buffer + readbuffer
                           

    def send(self, ircsock, command):
        try:
            answer = command.execute()
            ircsock.send(bytes("PRIVMSG {}\n\r".format(answer), "UTF-8"))
        
        except:
            raise
         

            
    ############################################################################################
    ############################################################################################


    ################################# atribute checking ########################################
    ############################################################################################

    #
    # TODO or not TODO
    #

    def check_host(host):
        return host

    def check_port(port):
        return port

    def check_nick(nick):
        return nick

    def check_channels(channel):
        return channel

    def check_database(database):
        return database

    def check_prefix(prefix):
        return prefix

    def check_password(password):
        return password

    def check_ssl(ssl):
        return ssl
              
    ############################################################################################
    ############################################################################################
