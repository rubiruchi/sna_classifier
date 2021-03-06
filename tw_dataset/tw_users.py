#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
from utils import json_dump_unicode, json_load_unicode, concatenate
import os
import time

import networkx as nx
import pickle, json
from datetime import timedelta, datetime
from twitter_api import API_HANDLER

from math import ceil

FAV_DAYS = 30

FAV_DATE_LIMIT = datetime.now() - timedelta(days=FAV_DAYS)

# GRAPH = nx.read_gpickle('big_graph.gpickle')

GRAPH = nx.read_graphml('big_graph.graphml')

RELEVANT_FNAME = "relevantdict.json"

if os.path.exists(RELEVANT_FNAME):
    with open(RELEVANT_FNAME, 'r') as f:
        RELEVANT = json.load(f)
else:
    RELEVANT = {}

def is_relevant(user_id):
    user_id = str(user_id)
    if user_id in RELEVANT:
        return RELEVANT[user_id]
    else:
        retries = 0
        while True:
            try:
                TW = API_HANDLER.get_connection()
                u = TW.get_user(user_id)
                relevant = u.followers_count > 40 and u.friends_count > 40
                RELEVANT[user_id] = relevant
                with open(RELEVANT_FNAME, 'w') as f:
                    json.dump(RELEVANT, f)
                return relevant
            except Exception, e:
                print "Error in is_relevant for %s" % user_id
                retries += 1
                if retries == 5:
                    print "Gave up retrying for user %s" % user_id
                    print "(marked as not relevant)"
                    return False
                else:
                    print "waiting..."
                    time.sleep(10)


def get_follower_counts(user_id):
    TW = API_HANDLER.get_connection()
    u = TW.get_user(user_id)
    return u.followers_count


def filter_most_relevant_users(user_ids, scoring_function, N=100):
    scored = [(u_id, scoring_function(u_id)) for u_id in user_ids]

    most_relevant = sorted(scored, key=lambda u, s: -s)[:N]

    return most_relevant


def get_my_most_popular_followed(N=100):
    my_id = USER_DATA['id']

    followed_ids = get_followed_user_ids(my_id)

    fname = 'followed.pickle'

    if os.path.exists(fname):
        with open(fname, 'rb') as f:
            scored = pickle.load(f)
    else:
        scored = []

    n_seen = len(scored)

    for i, u_id in enumerate(followed_ids[n_seen:]):
        scored.append((u_id, get_follower_counts(u_id)))
        if i > 0 and i % 10 == 0:
            with open(fname, 'wb') as f:
                pickle.dump(scored, f)
    
    most_popular = sorted(scored, key=lambda (u, s): -s)[:N]

    return most_popular


def get_most_similar_followed(user_id, amount=None, N=None):
    followed_ids = get_followed_user_ids(user_id=user_id)
    followed_ids = [f_id for f_id in followed_ids if is_relevant(f_id)]

    scored = []
    for u_id in followed_ids:
        u_followed_ids = set(get_followed_user_ids(user_id=u_id))
        common = len(u_followed_ids.intersection(set(followed_ids)))
        total = len(followed_ids) + len(u_followed_ids) - common
        score = common * 1.0 / total
        scored.append((u_id, score))

    if N is None:
        if amount is not None:
            N = ceil(amount * len(scored))
        else:
            raise ValueError("either N or amount must be passed")
    
    most_similar = sorted(scored, key=lambda (u, s): -s)[:N]
    most_similar = [u for (u, s) in most_similar]

    return most_similar


NOTAUTHORIZED_FNAME = "notauthorizedids.pickle"

if os.path.exists(NOTAUTHORIZED_FNAME):
    with open(NOTAUTHORIZED_FNAME, 'rb') as f:
        NOTAUTHORIZED = pickle.load(f)
else:
    NOTAUTHORIZED = set()


def get_followed_user_ids(user=None, user_id=None):
    if user is not None:
        user_id = user.id

    if GRAPH.out_degree(user_id):
        followed = GRAPH.successors(user_id)
        return followed
    else:
        retries = 0
        while True:
     
            try:
                TW = API_HANDLER.get_connection()
                followed = TW.friends_ids(user_id=user_id)
                GRAPH.add_edges_from([(user_id, f_id) for f_id in followed])
                return followed
            except Exception, e:
                # print e
                if e.message == u'Not authorized.':
                    NOTAUTHORIZED.add(user_id)
                    with open(NOTAUTHORIZED_FNAME, 'wb') as f:
                        pickle.dump(NOTAUTHORIZED, f)
                    return []
                else:
                    print "Error for user %d: %s" % (user_id, e.message)
                    retries += 1
                    if retries == 5:
                        print "Gave up retrying for user %d" % user_id
                        return [] 
                    else:
                        print "waiting..."
                        time.sleep(10)


TL_DAYS = 10

TL_DATE_LIMIT = datetime.now() - timedelta(days=TL_DAYS)


def fetch_favorites(user_id):
    favorites_file = "favorites/%s.json" % user_id

    print "Fetching favorites for user %d" % user_id
    start_time = time.time()
    if not os.path.exists(favorites_file):
        # authenticating here ensures a different set of credentials
        # everytime we start processing a new county, to prevent hitting the rate limit
        favorites = []

        page = 1
        done = False
        while not done:
            TW_API = API_HANDLER.get_fresh_connection()
            try:
                favs = TW_API.favorites(user_id=user_id, page=page)
            except Exception, e:                
                if e.message == u'Not authorized.':
                    NOTAUTHORIZED.add(user_id)
                    with open(NOTAUTHORIZED_FNAME, 'wb') as f:
                        pickle.dump(NOTAUTHORIZED, f)
                    break
                else:
                    print("Error: %s" % e.message)
                    print "waiting..."
                    time.sleep(10)
                    continue

            if favs:
                for t in favs:
                    if t.created_at > FAV_DATE_LIMIT:
                        favorites.append({
                                "timestamp": t.created_at.strftime("%Y/%m/%d %H:%M:%S"),
                                "text": t.text,
                                "user_id": t.user.id,
                                "id": t.id
                            })
                        json_dump_unicode(favorites, favorites_file + ".tmp")
                    else:
                        done = True
                        break
            else:
                # All done
                break
            page += 1  # next page

        if favorites:
            os.remove(favorites_file + ".tmp")
            json_dump_unicode(favorites, favorites_file)

    else:
        favorites = json_load_unicode(favorites_file)
    elapsed_time =  time.time() - start_time
    print "Done. Took %.1f secs to fetch %d favs" % (elapsed_time, len(favorites))

    return favorites

RT_DAYS = 10

RT_DATE_LIMIT = datetime.now() - timedelta(days=RT_DAYS)


def fetch_retweets(user_id):
    # NOT WORKING, need to fetch entire timeline
    retweets_file = "retweets/%s.json" % user_id

    print "Fetching retweets for user %d" % user_id
    start_time = time.time()
    if not os.path.exists(retweets_file):
        # authenticating here ensures a different set of credentials
        # everytime we start processing a new county, to prevent hitting the rate limit
        retweets = []

        page = 1
        done = False
        while not done:
            TW_API = API_HANDLER.get_fresh_connection()
            try:
                rts = TW_API.retweets(user_id=user_id, page=page)
            except Exception, e:                
                if e.message == u'Not authorized.':
                    NOTAUTHORIZED.add(user_id)
                    with open(NOTAUTHORIZED_FNAME, 'wb') as f:
                        pickle.dump(NOTAUTHORIZED, f)
                    break
                else:
                    print("Error: %s" % e.message)
                    print "waiting..."
                    time.sleep(10)
                    continue

            if rts:
                for t in rts:
                    if t.created_at > RT_DATE_LIMIT:
                        retweets.append({
                                "timestamp": t.created_at.strftime("%Y/%m/%d %H:%M:%S"),
                                "text": t.text,
                                "user_id": t.user.id,
                                "id": t.id
                            })
                        json_dump_unicode(retweets, retweets_file + ".tmp")
                    else:
                        done = True
                        break
            else:
                # All done
                break
            page += 1  # next page

        if retweets:
            os.remove(retweets_file + ".tmp")
            json_dump_unicode(retweets, retweets_file)

    else:
        retweets = json_load_unicode(retweets_file)
    elapsed_time =  time.time() - start_time
    print "Done. Took %.1f secs to fetch %d rts" % (elapsed_time, len(retweets))

    return retweets


def get_friends_graph():
    my_id = USER_DATA['id']

    # Seed: users I'm following
    my_followed = get_followed_user_ids(my_id)

    fname = 'graph.gpickle' 
    if os.path.exists(fname):     # resume
        graph = nx.read_gpickle(fname)
    else:
        graph = nx.DiGraph()

    seen = set([x[0] for x in graph.edges()])
    
    unvisited = list(set(my_followed) - seen)
    for u_id in unvisited:
        followed = get_followed_user_ids(u_id)
        nx.write_gpickle(graph, fname)

    return graph


def filter_relevant_ids(graph):
    """
        Dado el grafo de mis followed y sus followed,
        extraemos los 100 nodos más relevantes 
    """
    graph = nx.read_gpickle('graph.gpickle')
    my_followed = list(set([x[0] for x in graph.edges()]))
    graph = nx.subgraph(graph, my_followed)

    def get_nfollowed(nid):
        return len(graph.successors(nid))

    def get_nfollowers(nid):
        return len(graph.predecessors(nid))

    import pandas as pd
    df = pd.DataFrame()
    df['nodeid'] = my_followed
    df['nfollowed'] = df['nodeid'].apply(get_nfollowed)
    df['nfollowers'] = df['nodeid'].apply(get_nfollowers)

    relevant = df[(df.nfollowed > 40) & (df.nfollowers > 40)]

    relevantids = list(relevant.nodeid.values)
    with open('layer0.pickle','wb') as f:
        pickle.dump(relevantids, f)

    return relevantids


def extend_followed_graph(outer_layer_ids, level):
    """
        Given a graph and the ids of its outer layer,
        it extends it with one extra step in the followed
        relation.

        This is meant to be applied up to a certain number
        of steps. The outer layer are the nodes that were
        seen for the first time in the previous step

        Level 0 are just a set of selected relevant users.
        After that, level N + 1 is the extension of level N
        by one more step in the followed relation
    """
    fname_current = 'graph%d.gpickle' % level     
    if os.path.exists(fname_current):     # resume
        graph = nx.read_gpickle(fname_current)
        with open('layer%d.pickle' % level, 'rb') as fl:
            new_outer_layer = pickle.load(fl)
    else:
        # start from previous
        fname_previous = 'graph%d.gpickle' % (level - 1)
        graph = nx.read_gpickle(fname_previous)
        new_outer_layer = set()

    seen = set([x[0] for x in graph.edges()])
    unvisited = outer_layer_ids - seen
    for u_id in unvisited:
        followed = get_followed_user_ids(u_id)
        followed = [f_id for f_id in followed if is_relevant(f_id)]
        graph.add_edges_from([(u_id, f_id) for f_id in followed])
        
        new_nodes = [f_id for f_id in followed if graph.out_degree(f_id) == 0]
        new_outer_layer.update(new_nodes)
        
        nx.write_gpickle(graph, fname_current)
        with open('layer%d.pickle' % level, 'wb') as fl:
            pickle.dump(new_outer_layer, fl)

    return graph, new_outer_layer


def compute_extended_graphs():
    with open('layer0.pickle','rb') as f:
        outer_layer_ids = pickle.load(f)

    for level in [1, 2, 3]:
        graph, outer_layer_ids = extend_followed_graph(outer_layer_ids, level)


if __name__ == '__main__':
    compute_extended_graphs()
    # graph = get_friends_graph()

    # fname = 'graph.gpickle'
    # graph = nx.read_gpickle(fname)

    # for uid in graph.nodes():
    #     fetch_timeline(user_id=uid)
    # import matplotlib.pyplot as plt
    # nx.draw(graph)
    # plt.show()

    # user_ids = graph.nodes()

    # for u_id in user_ids:
    #     fetch_timeline(screen_name=None, user_id=None, days=30)

    # Among those, I collect all the following relationships within the set 
