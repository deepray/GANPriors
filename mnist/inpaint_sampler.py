import os
import numpy as np
import tensorflow as tf
import tensorflow.contrib.slim as slim
from config import argparser
from models_mnist import generator as gen
import tensorflow_probability as tfp

tfd= tfp.distributions
tf.reset_default_graph()
PARAMS = argparser()
np.random.seed(PARAMS.seed_no)

N = PARAMS.n_inpaint
burn = int(PARAMS.burn_inpaint*N)
z_dim = PARAMS.z_dim
batch_size = PARAMS.batch_size # should always be one
noise_var = PARAMS.noise_var
dim_like = PARAMS.img_h*PARAMS.img_w*PARAMS.img_c



'''data'''
test_data = np.load('test_set/test_x.npy')
test_sample = np.reshape(test_data[PARAMS.digit_array[PARAMS.digit]], [PARAMS.img_h, PARAMS.img_w, PARAMS.img_c])
meas_path = './meas/full_gaussian_noisevar{}'.format(PARAMS.noise_var)
save_dir = './exps/inpaint_exps/digit{}_var{}_N{}_strow{}_endrow{}_stcol{}_endcol{}'.format(PARAMS.digit, noise_var, N, 
                                                                                PARAMS.start_row, PARAMS.end_row, PARAMS.start_col, PARAMS.end_col)
if not os.path.exists(save_dir):
    os.makedirs(save_dir)  
    
if not os.path.exists(meas_path):
    print('***** Measurement does not exist !! *****')
    print('** Generating one with noise_var={} **'.format(PARAMS.noise_var))
    os.makedirs(meas_path)
    noise_mat3d = np.random.multivariate_normal(mean=np.zeros((dim_like)), cov=np.eye(dim_like, dim_like)*PARAMS.noise_var, size=1)    
    np.save(meas_path+'/noise_mat3d.npy', noise_mat3d)    
else:
    noise_mat3d = np.load(meas_path+'/noise_mat3d.npy')
      
y_hat3d = test_sample + np.reshape(noise_mat3d, [PARAMS.img_h, PARAMS.img_w, PARAMS.img_c])
y_hat4d = np.tile(y_hat3d, (PARAMS.batch_size, 1, 1, 1)).astype(np.float32)
np.save(save_dir+'/y_hat4d.npy', y_hat4d)


# inpaint mask
mask = np.ones((batch_size, PARAMS.img_h, PARAMS.img_w, PARAMS.img_c))
mask[:, PARAMS.start_row:PARAMS.end_row, PARAMS.start_col:PARAMS.end_col, :] = 0.
dim_inpaint = int(np.sum(mask))
np.save(save_dir+'/mask.npy', mask)



# tflow graph for posterior computation
with tf.Graph().as_default() as g:
    def joint_log_prob(z):              
        gen_out = gen(z, reuse=tf.AUTO_REUSE, training=False)
        diff_img = gen_out - tf.constant(y_hat4d)
        visible_img = tf.boolean_mask(diff_img, mask)
        
        prior = tfd.MultivariateNormalDiag(loc=np.zeros(z_dim, dtype=np.float32), scale_diag=np.ones(z_dim, dtype=np.float32))
        like = tfd.MultivariateNormalDiag(loc=np.zeros(dim_inpaint, dtype=np.float32), scale_diag=np.sqrt(noise_var)*np.ones(dim_inpaint, dtype=np.float32))
        
        return (prior.log_prob(z) + like.log_prob(visible_img))
                                          

    def unnormalized_posterior(z):
        return joint_log_prob(z) 
    adaptive_hmc = tfp.mcmc.SimpleStepSizeAdaptation(
                    tfp.mcmc.HamiltonianMonteCarlo(target_log_prob_fn=unnormalized_posterior, step_size=np.float32(1.), num_leapfrog_steps=3),
                   num_adaptation_steps=int(0.8*burn))
    

    initial_state = tf.constant(np.random.normal(size=[batch_size, z_dim]).astype(np.float32))
    samples, [st_size, log_accept_ratio] = tfp.mcmc.sample_chain(
      num_results=N,
      num_burnin_steps=burn,
      current_state=initial_state,
      kernel=adaptive_hmc,
      trace_fn=lambda _, pkr: [pkr.inner_results.accepted_results.step_size,
                             pkr.inner_results.log_accept_ratio])
    p_accept = tf.reduce_mean(tf.exp(tf.minimum(log_accept_ratio, 0.)))

     
    zz = tf.placeholder(tf.float32, shape=[N-burn, z_dim])    
    gen_out1 = gen(zz, reuse=tf.AUTO_REUSE, training=False)
    
    variables_to_restore = slim.get_variables_to_restore()   
    saver = tf.train.Saver(variables_to_restore)
    

with tf.Session(graph=g) as sess:
    
    saver.restore(sess, PARAMS.model_path)    
    
    samples_ = sess.run(samples)
    np.save(save_dir+'/samples.npy', samples_)
    print('HMC acceptance ratio = {}'.format(sess.run(p_accept)))
