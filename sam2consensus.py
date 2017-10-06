#!/usr/bin/env python2

'''
The program takes as input a SAM file resulting from mapping short reads to a collection of
gene sequences as reference, then it calculates the consensus sequence per gene without
considering the reference. It adds insertions and can take a custom consensus threshold,
the consensus method is the same as the one described for Geneious
(http://assets.geneious.com/manual/8.1/GeneiousManualse41.html).

Input SAM files have to be sorted, contain only mapped reads (preferably), and have
CIGAR strings in SAM v.1.3. Original reference FASTAs are not necessary.

It will produce a FASTA sequence per gene, and in case the gene has insertions it will also create
a separate SAM file just for the particular gene for verification purposes.
'''

__author__      = "Edgardo M. Ortiz"
__credits__     = "Deise J.P. Goncalves"
__version__     = "1.0"
__email__       = "e.ortiz.v@gmail.com"
__date__        = "2017-10-06"

import sys
import re
import operator

filename = sys.argv[1]		             # First argument is the name of the SAM file
try:cons_threshold = float(sys.argv[2])  # Second argument is the percentage fo consensus, defaults to 0.25
except (ValueError, IndexError): cons_threshold = 0.25

specimen = '_'.join(filename.split('_')[0:3])
print 'Processing specimen '+specimen+'...\n'

organelle = filename.split('.')[1]

def parsecigar(cigarstring, seq, pos_ref):
    '''
    Modifies a sequence according to its CIGAR string

    :param cigarstring: cigar string, check SAM format specification
    :param seq: raw sequence
    :param pos_ref: position in the reference of the leftmost aligned nucleotide
    :return: edited sequence according to cigar string, list of tuples for
             insertions indicating coordinate in the reference and the
             sequence inserted
    '''

    matches = re.findall(r'(\d+)([A-Z]{1})', cigarstring)
    cigar = [{'type': m[1], 'length': int(m[0])} for m in matches]
    start = 0
    start_ref = pos_ref
    seqout = ''
    insert = []
    for i in range(0, len(cigar)):
        l = cigar[i]['length']
        if cigar[i]['type'] == 'S':
            start += l
        elif cigar[i]['type'] == 'H':
            continue
        elif cigar[i]['type'] == 'M':
            seqout += seq[start:start + l]
            start += l
            start_ref += l
        elif cigar[i]['type'] == 'I':
            insert.append((start_ref, seq[start:start+l]))
            start += l
        elif cigar[i]['type'] == 'D':
            seqout += '-' * l
            start_ref += l
        else:
            print 'SAM file probably contains unmapped reads'
    return seqout, insert

''' Process the SAM file in a single pass '''
with open(filename) as mapfile:
    genes = {}                                              # Container of sequences per gene
    insertions = {}                                         # Container for insertions with coordinates per gene
    gene_previous = ''                                      # Stores name of previous gene processed
    sam_file = ['@HD'+'\t'+'VN:1.3'+'\t'+'SO:coordinate']   # Header for SAM files of genes with insertions
    sam_reads = []                                          # Container for reads to be written to the SAM

    for line in mapfile:
        ''' Extract gene names '''
        if line[0:3] == '@SQ':

            ''' Obtain the name of the first gene in the file '''
            if gene_previous == '':
                gene_previous = line.split('\t')[1].replace('SN:','')

            ''' Populate empty dictionary, values to be store in a list per gene '''
            genes[line.split('\t')[1].replace('SN:','')] = []
            insertions[line.split('\t')[1].replace('SN:','')] = []

            ''' Populate each gene with as many empty nucleotides as the reference '''
            for nuc in range(0, int(line.split('\t')[2].replace('LN:',''))):
                genes[line.split('\t')[1].replace('SN:','')].append({'A':0,'C':0,'T':0,'G':0,'-':0,'N':0})

            ''' Also add the length of each gene after the list of nucleotides '''
            genes[line.split('\t')[1].replace('SN:','')].append(int(line.split('\t')[2].replace('LN:','')))

        # Start processing the aligned reads, skip unaligned [*]
        elif line[0] != '@' and line.split('\t')[5] != '*':
            gene_current = line.split('\t')[2]

            ''' If we haven't started processing the next gene... '''
            if gene_current == gene_previous:
                pos_ref = int(line.split('\t')[3]) - 1              # Starting position in the reference
                cigar = line.split('\t')[5]                         # CIGAR string fo the aligned read
                seqraw = line.split('\t')[9]                        # Unaltered sequence of the aligned read
                seqout, insert = parsecigar(cigar, seqraw, pos_ref) # Parse the CIGAR and obtain edited sequence
                                                                    # and list of insertions
                
                ''' Fill the nucleotides in the respective gene according to the
                    sequence processed according to its CIGAR string '''
                for i in range(0,len(seqout)):
                    genes[gene_current][i+pos_ref][seqout[i]] += 1

                ''' Add insertions with coordinates to the dictionary of insertions per gene '''
                for j in insert:
                    insertions[gene_current].append(j)

                ''' Update name of previous gene with current '''
                gene_previous = gene_current

                ''' Add the read in case a SAM is produced for this gene '''
                sam_reads.append(line.strip('\n'))

            # If we started processing the next gene, stop and summarize the previous gene,
            # then continue as normal...
            else:
                ''' Calculate average coverage per base and add to the gene info '''
                nuc_covs = 0
                for pos in range(0, (len(genes[gene_previous])-1)):
                    nuc_covs += sum(genes[gene_previous][pos].values())
                cov_average = float(nuc_covs/genes[gene_previous][-1])
                genes[gene_previous].append(cov_average)

                ''' Find real insertions based on coverage of adjacent nucleotides '''
                real_insertions_coordinates = []
                real_insertions_motifs = []
                for ins in sorted(set(insertions[gene_previous])):

                    ''' Get the average coverage of the nucleotide before and after the insertion '''
                    cov_at_edges = float((sum(genes[gene_previous][ins[0]].values())+sum(genes[gene_previous][ins[0]+1].values()))/2)

                    ''' If the insertion has acceptable coverage accept it as real '''
                    if insertions[gene_previous].count(ins) > cov_at_edges*0.97*(1-cons_threshold):
                        real_insertions_coordinates.append(ins[0])
                        real_insertions_motifs.append(ins[1])
                        print 'Insertion detected, coverage at sides of insertion: '+str(cov_at_edges)+', insertion coverage: '+str(insertions[gene_previous].count(ins))+', coord/motif: '+str(ins)

                ''' If the gene has real insertions produce a SAM for verification and
                    eliminate insertions with low coverage (errors) '''
                if real_insertions_coordinates != []:
                    print gene_previous.split('_')[1]+' contains insertion(s), a separate SAM file will be additionally created for this gene.'
                    sam_file.append('@SQ'+'\t'+'SN:'+gene_previous+'\t'+'LN:'+str(genes[gene_previous][-2]))
                    for read in sam_reads:
                        sam_file.append(read)
                    outfile = open(gene_previous.split('_')[1]+'_'+specimen+'.sam', 'w')
                    outfile.write('\n'.join(sam_file)+'\n')
                    insertions[gene_previous] = [real_insertions_coordinates,real_insertions_motifs]
                else:
                    del insertions[gene_previous]

                ''' Reset SAM header, empty list of SAM reads '''
                sam_file = ['@HD'+'\t'+'VN:1.3'+'\t'+'SO:coordinate']
                sam_reads = []
                print 'Gene '+gene_previous.split('_')[1]+' processed\n'

                ''' Process current read as in line 92 '''
                pos_ref = int(line.split('\t')[3]) - 1
                cigar = line.split('\t')[5]
                seqraw = line.split('\t')[9]
                seqout, insert = parsecigar(cigar, seqraw, pos_ref)
                for i in range(0,len(seqout)):
                    genes[gene_current][i+pos_ref][seqout[i]] += 1
                for j in insert:
                    insertions[gene_current].append(j)
                gene_previous = gene_current
                sam_reads.append(line.strip('\n'))

    ''' For the last read of the last gene only, 
        same process as line 117 '''
    nuc_covs = 0
    for pos in range(0, (len(genes[gene_current])-1)):
        nuc_covs += sum(genes[gene_current][pos].values())
    cov_average = float(nuc_covs/genes[gene_current][-1])
    genes[gene_current].append(cov_average)

    real_insertions_coordinates = []
    real_insertions_motifs = []
    for ins in sorted(set(insertions[gene_current])):
        cov_at_edges = float((sum(genes[gene_current][ins[0]].values())+sum(genes[gene_current][ins[0]+1].values()))/2)
        if insertions[gene_current].count(ins) >= cov_at_edges*0.97*(1-cons_threshold): # 0.97 to account for errors not contributing to coverage of insertion
            real_insertions_coordinates.append(ins[0])
            real_insertions_motifs.append(ins[1])
            print 'Insertion detected: coverage at sides of insertion: '+str(cov_at_edges)+', insertion coverage: '+str(insertions[gene_current].count(ins))+', coord/motif: '+str(ins)
    
    if real_insertions_coordinates != []:
        print gene_current.split('_')[1]+' contains insertion(s), a separate SAM file will be additionally created for this gene.'
        sam_file.append('@SQ'+'\t'+'SN:'+gene_current+'\t'+'LN:'+str(genes[gene_current][-2]))
        for read in sam_reads:
            sam_file.append(read)
        outfile = open(gene_current.split('_')[1]+'_'+specimen+'.sam', 'w')
        outfile.write('\n'.join(sam_file)+'\n')
        insertions[gene_current] = [real_insertions_coordinates,real_insertions_motifs]
    else:
        del insertions[gene_current]
    print genes
    print 'Gene '+gene_current.split('_')[1]+' processed\n'

''' Dictionary to translate ambiguities IUPAC '''
amb = {('-','A'):'A',
       ('-','C'):'C',
       ('-','G'):'G',
       ('-','N'):'-',
       ('-','T'):'T',
       ('A','C'):'M',
       ('A','G'):'R',
       ('A','N'):'A',
       ('A','T'):'W',
       ('C','G'):'S',
       ('C','N'):'C',
       ('C','T'):'Y',
       ('G','N'):'G',
       ('G','T'):'K',
       ('N','T'):'T'}

''' Obtain sequence from the 'genes' dictionary '''
fastas = {}
for gene in genes.keys():
    for pos in range(0, genes[gene][-2]):
        count_nucs = list(sorted(genes[gene][pos].iteritems(), key=operator.itemgetter(1), reverse=True)[:2])
        cov_site = sum(genes[gene][pos].values())
        if count_nucs[0][1] >= cons_threshold*cov_site:
            if gene not in fastas:
                fastas[gene] = count_nucs[0][0]
            else:
                fastas[gene] += count_nucs[0][0]
        else:
            if gene not in fastas:
                fastas[gene] = amb[tuple(sorted((count_nucs[0][0],count_nucs[1][0])))]
            else:
                fastas[gene] += amb[tuple(sorted((count_nucs[0][0],count_nucs[1][0])))]

''' Add insertions for genes with real insertions '''
for gene in insertions.keys():
    seq = fastas[gene]
    start = 0
    seqout = ''
    for i in range(0, len(insertions[gene][0])):
        seqout += seq[start:insertions[gene][0][i]]
        seqout += insertions[gene][1][i]
        start = insertions[gene][0][i]
    seqout += seq[insertions[gene][0][-1]:]
    fastas[gene] = seqout

''' Write fasta output files '''
for gene in fastas:
    outfile = open(gene.split('_')[1]+'_'+organelle+'_'+specimen+'.fasta', 'w')
    outfile.write('>'+specimen[:-3]+' '+specimen[:-3]+', '+gene.split('_')[1]+', '+organelle+', coverage '+str(genes[gene][-1])+'\n'+fastas[gene]+'\n')

''' END '''
